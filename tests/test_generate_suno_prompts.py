"""generate_suno_prompts CLI / generate() の挙動テスト."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from youtube_automation.scripts.generate_suno_prompts import build_prompt_entries, generate, main
from youtube_automation.utils import skill_config

# `_skills/<skill>/config.default.yaml` の解決元になる editable install のソースツリー
_DEFAULT_YAML = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "suno" / "config.default.yaml"
_SUNO_LYRIC_DEFAULT_YAML = (
    Path(__file__).resolve().parents[1] / ".claude" / "skills" / "suno-lyric" / "config.default.yaml"
)
_SKILL_MD = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "suno" / "SKILL.md"
_CONFIG_RULES_MD = (
    Path(__file__).resolve().parents[1]
    / ".claude"
    / "skills"
    / "channel-setup"
    / "references"
    / "config-generation-rules.md"
)


@pytest.fixture
def channel_dir(tmp_path, monkeypatch):
    """skill_config が参照する CHANNEL_DIR を一時ディレクトリへ向ける."""
    ch = tmp_path / "channel"
    (ch / "config" / "skills").mkdir(parents=True)
    monkeypatch.setenv("CHANNEL_DIR", str(ch))
    skill_config.reset()
    yield ch
    skill_config.reset()


def _write_minimal_patterns(dir_: Path) -> Path:
    """1 パターン × 1 シーンの最小 suno-patterns.yaml を作る.

    yaml top-level に `tracks: 2` を併設して `tracks_per_collection` の
    fail-loud 検証 (ceil(2/2) = 1 entry) と整合させる。
    """
    path = dir_ / "patterns.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "title": "Test Collection",
                "mode": "instrumental",
                "tracks": 2,
                "patterns": [
                    {
                        "name_jp": "テスト",
                        "name_en": "Test",
                        "tempo": "slow",
                        "scenes": ["a quiet scene description"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_suno_override(channel: Path, **overrides) -> None:
    """channel 側の config/skills/suno.yaml を生成する."""
    (channel / "config" / "skills" / "suno.yaml").write_text(yaml.safe_dump(overrides), encoding="utf-8")


def _write_video_analysis(
    channel: Path,
    *,
    slug: str,
    video_id: str,
    suno_preset: dict | None,
) -> Path:
    """`data/video_analysis/<slug>/<video_id>.json` を書き出す.

    `suno_preset=None` のときは preset キー自体を含めず欠落耐性を検証できる。
    """
    out_dir = channel / "data" / "video_analysis" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "video_id": video_id,
        "slug": slug,
        "bgm_arc": {"intro": "0:00-0:15", "peak": "1:30", "outro": "4:00-end"},
    }
    if suno_preset is not None:
        payload["suno_preset"] = suno_preset
    out_path = out_dir / f"{video_id}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def test_help_flag_shows_usage_and_exits_zero(monkeypatch, capsys):
    """--help は argparse の usage を表示して exit 0 する."""
    monkeypatch.setattr(sys, "argv", ["yt-generate-suno", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "usage" in captured.out.lower()


# ---------------------------------------------------------------------------
# issue #128: duration_prompt 完全削除の回帰テスト
# ---------------------------------------------------------------------------


def test_default_yaml_does_not_define_duration_prompt():
    """同梱の config.default.yaml に duration_prompt キーが存在しないこと."""
    data = yaml.safe_load(_DEFAULT_YAML.read_text(encoding="utf-8"))
    assert "duration_prompt" not in data, (
        "duration_prompt は issue #128 で完全削除された。default.yaml から該当行を削除すること。"
    )


def test_generate_output_contains_no_duration_phrases(channel_dir, tmp_path):
    """生成されたプロンプトに `long-form performance` 系の長さ指定文字列が含まれないこと."""
    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano")
    patterns_path = _write_minimal_patterns(tmp_path)

    output = generate(patterns_path)

    assert "long-form performance" not in output
    assert "4 to 5 minutes" not in output
    assert "over 4 minutes" not in output


def test_generate_styles_block_has_only_tempo_and_style(channel_dir, tmp_path):
    """Styles 行が `<tempo>, <effective_style>,` のみで構成されること.

    duration_prompt 由来の 3 要素目が付加されていないことを行レベルで固定する。
    """
    genre = "lo-fi jazz, soft piano"
    _write_suno_override(channel_dir, genre_line=genre)
    patterns_path = _write_minimal_patterns(tmp_path)

    output = generate(patterns_path)

    # Styles ブロックの中身は ``` で囲まれた 2 行 (style 行 + scene 行)。
    # 行頭・行末が完全一致することを行リストレベルで固定 (substring 一致では duration が
    # 後続に付加されたケースを検出できないため)。
    expected_style_line = f"slow, {genre},"
    lines = output.splitlines()
    assert expected_style_line in lines, (
        f"Styles 行が想定形式になっていない (完全一致なし). expected line: `{expected_style_line}`"
    )


def test_generate_ignores_legacy_duration_prompt_in_channel_override(channel_dir, tmp_path):
    """チャンネル override に旧 `duration_prompt` キーが残っていても出力に影響しないこと.

    削除前のコードを参照しているチャンネル (rain-jazz-night など) は、暫定対応で
    `duration_prompt: ""` を override に入れている。今回の削除でキー読み取り自体が
    無くなるため、override にどんな値が残っていても出力には現れない。
    """
    sentinel = "DURATION_PROMPT_LEGACY_MARKER_SHOULD_NOT_APPEAR"
    _write_suno_override(
        channel_dir,
        genre_line="lo-fi jazz",
        duration_prompt=sentinel,
    )
    patterns_path = _write_minimal_patterns(tmp_path)

    output = generate(patterns_path)

    assert sentinel not in output


def test_generate_styles_block_no_trailing_duration_token(channel_dir, tmp_path):
    """Styles 行末尾のカンマ位置に duration_prompt 残骸が紛れ込んでいないこと."""
    _write_suno_override(channel_dir, genre_line="lo-fi jazz")
    patterns_path = _write_minimal_patterns(tmp_path)

    output = generate(patterns_path)

    # Styles ブロックを 1 つだけ抽出して構造を検査する
    in_styles = False
    styles_body: list[str] = []
    for line in output.splitlines():
        if line == "**Styles:**":
            in_styles = True
            continue
        if in_styles:
            if line == "```" and not styles_body:
                # opening fence
                continue
            if line == "```":
                break
            styles_body.append(line)

    # 1 行目が `<tempo>, <style>,`、2 行目が scene の 2 行構成
    assert len(styles_body) == 2, f"Styles ブロックが 2 行ではない: {styles_body!r}"
    style_line = styles_body[0]
    # カンマ区切りの要素が tempo + style の 2 個 + 末尾区切りの空要素 = 3 トークン
    tokens = [t.strip() for t in style_line.split(",")]
    assert tokens[-1] == "", "末尾カンマ仕様 (`...,` で終わる) が壊れている"
    non_empty = [t for t in tokens if t]
    assert len(non_empty) == 2, (
        f"Styles 1 行目は tempo + style の 2 要素のみ。duration_prompt 残骸の可能性: {non_empty!r}"
    )


# ---------------------------------------------------------------------------
# SKILL.md 側のドキュメント変更を固定する回帰テスト
# ---------------------------------------------------------------------------


def test_skill_md_does_not_reference_duration_prompt():
    """SKILL.md から duration_prompt の参照と V5.5 で長さが効くという誤記が消えていること."""
    text = _SKILL_MD.read_text(encoding="utf-8")

    assert "duration_prompt" not in text, (
        "SKILL.md にまだ `duration_prompt` の言及が残っている。"
        "issue #128 で参照を完全削除すること (L242 のスクリプト説明文を含む)。"
    )
    assert "long-form performance, over 4 minutes, 4 to 5 minutes" not in text, (
        "SKILL.md に旧 duration_prompt の例文が残っている。削除すること。"
    )


def test_skill_md_describes_extend_for_length_control():
    """SKILL.md の「曲の長さ」記述が Extend 中心に書き換わっていること.

    変更前: 「V5.5 では Styles に時間指定プロンプトが反映されるようになった」と誤記。
    変更後: 「V5.5 では Styles で実楽曲長を制御できない / 短い場合は Extend で延長」へ。
    """
    text = _SKILL_MD.read_text(encoding="utf-8")

    # Extend による延長が長さ調整の手段として案内されていること
    assert "Extend" in text, "SKILL.md に Extend (Suno の延長機能) の記述が無い。曲が短いときの対処として明記すること。"

    # 旧誤記が削除されていること: V5.5 で Styles 経由の時間指定が効くという表現
    forbidden_phrases = (
        "Styles に時間指定プロンプトが反映",
        "Styles での時間指定を優先",
    )
    for phrase in forbidden_phrases:
        assert phrase not in text, (
            f"SKILL.md に旧誤記 (`{phrase}`) が残っている。"
            "Suno V5.5 では Styles 経由で楽曲長を制御できないため、"
            "該当記述は削除すること。"
        )


def test_skill_md_warns_about_genre_line_exclude_styles_conflict():
    """SKILL.md に genre_line と exclude_styles の矛盾防止ガイドが追記されていること.

    order.md「提案する変更 2」の趣旨:
    `exclude_styles` で除外したワードを `genre_line` 側に残すと相殺される、
    という注意書きを SKILL.md 上に独立した節として追記する。

    別ジャンルへ書き換えても壊れないよう、以下を構造的に検査する:

    1. 専用見出しが存在する（`#### genre_line と exclude_styles の整合性`）
    2. その節に `genre_line` と `exclude_styles` の両ワードが含まれる
    """
    text = _SKILL_MD.read_text(encoding="utf-8")

    heading = "#### genre_line と exclude_styles の整合性"
    assert heading in text, (
        f"SKILL.md に専用見出し ({heading!r}) が存在しない。"
        "order.md 提案の矛盾防止ガイドを独立した節として追記すること。"
    )

    # 見出しから次の見出しまでをガイド本体として切り出して両概念名の存在を検査する
    after_heading = text.split(heading, 1)[1]
    next_heading_idx = after_heading.find("\n#")
    section_body = after_heading if next_heading_idx == -1 else after_heading[:next_heading_idx]
    for term in ("genre_line", "exclude_styles"):
        assert term in section_body, (
            f"`{heading}` 節に `{term}` への言及がない。"
            "矛盾防止ガイドは genre_line / exclude_styles 双方を扱う必要がある。"
        )


# ---------------------------------------------------------------------------
# issue #586: 歌詞関連 config の後方互換
# ---------------------------------------------------------------------------


def test_suno_default_yaml_does_not_own_lyric_authoring_config():
    """`/suno` は Style / merge 専任で、歌詞生成 config を持たない."""
    suno_data = yaml.safe_load(_DEFAULT_YAML.read_text(encoding="utf-8"))
    suno_lyric_data = yaml.safe_load(_SUNO_LYRIC_DEFAULT_YAML.read_text(encoding="utf-8"))

    assert "lyrics_guidelines" not in suno_data
    assert "lyrics_generation" not in suno_data
    assert suno_lyric_data["lyrics_generation"]["provider"] == "claude"


def test_suno_lyric_default_yaml_defines_cta_and_safe_quote_source_contract():
    """suno-lyric の SKILL.md が参照する config path を default YAML に持つ."""
    data = yaml.safe_load(_SUNO_LYRIC_DEFAULT_YAML.read_text(encoding="utf-8"))

    assert data["cta"]["positions"] == []
    assert data["source"]["base_url"] == "https://iyashitour.com"
    assert data["source"]["index_path"].startswith("/meigen/")


def test_channel_setup_rules_list_suno_lyrics_override_keys():
    text = _CONFIG_RULES_MD.read_text(encoding="utf-8")

    assert "config/skills/suno-lyric.yaml" in text
    assert "| suno-lyric | `config/skills/suno-lyric.yaml` |" in text
    assert "lyrics_guidelines.style_reference" not in text
    assert "lyrics_generation.provider" not in text


# ---------------------------------------------------------------------------
# issue #360: video_analysis の suno_preset を fallback として参照する動作
# ---------------------------------------------------------------------------


def test_fallback_uses_video_analysis_genre_line_when_config_empty(channel_dir, tmp_path):
    """`config/skills/suno.yaml` 空欄時、video_analysis JSON の genre_line を採用."""
    _write_suno_override(channel_dir)  # 空 override
    _write_video_analysis(
        channel_dir,
        slug="ref-channel",
        video_id="vid001",
        suno_preset={
            "genre_line": "lo-fi jazz, soft piano, warm rhodes",
            "exclude_styles": "",
            "rationale": "",
        },
    )
    patterns_path = _write_minimal_patterns(tmp_path)

    output = generate(patterns_path)

    assert "lo-fi jazz" in output
    assert "soft piano" in output
    assert "warm rhodes" in output


def test_fallback_uses_video_analysis_exclude_styles_when_config_empty(channel_dir, tmp_path):
    """`config/skills/suno.yaml` 空欄時、video_analysis JSON の exclude_styles を採用."""
    _write_suno_override(channel_dir, genre_line="lo-fi jazz")  # exclude_styles だけ空
    _write_video_analysis(
        channel_dir,
        slug="ref-channel",
        video_id="vid001",
        suno_preset={
            "genre_line": "ignored",
            "exclude_styles": "heavy metal, EDM, dubstep",
            "rationale": "",
        },
    )
    patterns_path = _write_minimal_patterns(tmp_path)

    output = generate(patterns_path)

    assert "**Exclude Styles:**" in output
    assert "heavy metal" in output
    assert "EDM" in output
    assert "dubstep" in output


def test_user_override_wins_over_video_analysis_fallback(channel_dir, tmp_path):
    """`config/skills/suno.yaml` に override があれば video_analysis 側は無視."""
    _write_suno_override(channel_dir, genre_line="ambient piano")
    _write_video_analysis(
        channel_dir,
        slug="ref-channel",
        video_id="vid001",
        suno_preset={
            "genre_line": "lo-fi jazz, soft piano",
            "exclude_styles": "heavy metal",
            "rationale": "",
        },
    )
    patterns_path = _write_minimal_patterns(tmp_path)

    output = generate(patterns_path)

    assert "ambient piano" in output
    # fallback 側の特徴語が漏れていないこと
    assert "lo-fi jazz" not in output
    assert "soft piano" not in output


def test_missing_suno_preset_falls_back_silently(channel_dir, tmp_path):
    """JSON に `suno_preset` キーが欠落していても例外を投げず default 動作."""
    _write_suno_override(channel_dir)  # 全て空
    # suno_preset なしの旧形式 JSON
    _write_video_analysis(
        channel_dir,
        slug="ref-channel",
        video_id="vid001",
        suno_preset=None,
    )
    patterns_path = _write_minimal_patterns(tmp_path)

    # 例外を投げずに生成完了すること
    output = generate(patterns_path)

    # genre_line が空のままなので Styles 行に何も追加されない
    assert "lo-fi jazz" not in output


def test_aggregates_multiple_video_analysis_jsons(channel_dir, tmp_path):
    """2 slug × 複数 JSON で genre_line 多数決・exclude_styles 和集合が機能する."""
    _write_suno_override(channel_dir)  # 空 override で fallback 強制

    # slug A: 2 件、共通 "lo-fi jazz" / 各自固有句あり
    _write_video_analysis(
        channel_dir,
        slug="ref-a",
        video_id="a1",
        suno_preset={
            "genre_line": "lo-fi jazz, soft piano",
            "exclude_styles": "heavy metal",
            "rationale": "",
        },
    )
    _write_video_analysis(
        channel_dir,
        slug="ref-a",
        video_id="a2",
        suno_preset={
            "genre_line": "lo-fi jazz, warm rhodes",
            "exclude_styles": "EDM",
            "rationale": "",
        },
    )
    # slug B: 1 件、新規句と既出除外語
    _write_video_analysis(
        channel_dir,
        slug="ref-b",
        video_id="b1",
        suno_preset={
            "genre_line": "lo-fi jazz, mellow drums",
            "exclude_styles": "heavy metal, dubstep",
            "rationale": "",
        },
    )

    patterns_path = _write_minimal_patterns(tmp_path)
    output = generate(patterns_path)

    # genre_line: "lo-fi jazz" が 3 票で先頭、他の句も上位 8 句に含まれる
    assert "lo-fi jazz" in output
    assert "soft piano" in output
    assert "warm rhodes" in output
    assert "mellow drums" in output

    # exclude_styles: 和集合で重複排除されつつ全種が現れる
    assert "heavy metal" in output
    assert "EDM" in output
    assert "dubstep" in output

    # genre_line の出現順は多数決優先 — "lo-fi jazz" が他の単発句より先
    lo_fi_idx = output.find("lo-fi jazz")
    soft_piano_idx = output.find("soft piano")
    assert lo_fi_idx < soft_piano_idx


# ---------------------------------------------------------------------------
# issue #692: suno-prompts.json 併出（build_prompt_entries / main の JSON 出力）
#
# 契約: `build_prompt_entries(patterns_path) -> list[dict]` を md 出力と同じ
# 部品から派生させ、`main()` が suno-prompts.md と同ディレクトリに
# suno-prompts.json を併出する。JSON entry は `{name, style, lyrics}` の 3 キー固定。
# ---------------------------------------------------------------------------


def _write_vocal_patterns(dir_: Path, scenes: list[str]) -> Path:
    """vocal モードの suno-patterns.yaml を作る（scene 数は可変）."""
    path = dir_ / "patterns.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "title": "Vocal Collection",
                "mode": "vocal",
                "patterns": [
                    {
                        "name_jp": "歌もの",
                        "name_en": "Vocal",
                        "tempo": "mid",
                        "scenes": scenes,
                        "lyrics": "[Verse]\nla la la\n\n",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_suno_lyrics_json(dir_: Path, names: list[str], *, lyrics: str = "[Verse]\nexternal lyric\n") -> Path:
    path = dir_ / "suno-lyrics.json"
    path.write_text(
        json.dumps([{"name": name, "lyrics": lyrics} for name in names], ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_build_prompt_entries_returns_name_style_lyrics_schema(channel_dir, tmp_path):
    """Given 最小 patterns
    When build_prompt_entries を呼ぶ
    Then 各 entry が {name, style, lyrics} の 3 キー（全て str）のみを持つ。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano")
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    assert isinstance(entries, list)
    assert len(entries) == 1
    entry = entries[0]
    # #900: strict 等価 (== {...}) から subset 検証へ緩和。More Options 3 フィールド
    # (style_influence / weirdness / exclude_styles) が channel override にあれば追加されうるため、
    # base 3 キーが必ず含まれることのみを担保する (追加キー無しの厳密検証は backward-compat 専用
    # テスト test_build_prompt_entries_omits_advanced_fields_without_channel_override が担う)。
    assert {"name", "style", "lyrics"} <= set(entry)
    assert all(isinstance(entry[key], str) for key in ("name", "style", "lyrics"))


def test_build_prompt_entries_name_combines_jp_and_en(channel_dir, tmp_path):
    """Given 単一 scene の pattern
    When name を読む
    Then `name_jp — name_en` 形式で Variation 接尾辞は付かない。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz")
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    assert entries[0]["name"] == "テスト — Test"


def test_build_prompt_entries_instrumental_has_empty_lyrics(channel_dir, tmp_path):
    """Given instrumental モード + auto_lyrics_structure: false
    When lyrics を読む
    Then 空文字（キーは常に存在し、None ではない）。

    auto_lyrics_structure が true (default) の場合は [Instrumental] + [Extended Outro] が
    自動付加されるため、空文字を期待するテストでは明示的に false にする。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano", auto_lyrics_structure=False)
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    assert entries[0]["lyrics"] == ""


def test_build_prompt_entries_style_contains_tempo_genre_and_scene(channel_dir, tmp_path):
    """Given tempo + genre_line + scene
    When style を読む
    Then md の Styles 行（`<tempo>, <style>,`）と scene の双方を含む。
    """
    genre = "lo-fi jazz, soft piano"
    _write_suno_override(channel_dir, genre_line=genre)
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    style = entries[0]["style"]
    assert f"slow, {genre}," in style
    assert "a quiet scene description" in style


def test_build_prompt_entries_style_excludes_exclude_styles(channel_dir, tmp_path):
    """Given exclude_styles 設定あり
    When style を読む
    Then exclude_styles のワードは style に含まれない（注入は Style/Lyrics の 2 欄のみ）。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz", exclude_styles="heavy metal, EDM")
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    style = entries[0]["style"]
    assert "heavy metal" not in style
    assert "EDM" not in style


def test_build_prompt_entries_vocal_includes_rstripped_external_lyrics(channel_dir, tmp_path):
    """Given vocal モード + 末尾改行付き suno-lyrics.json + auto_lyrics_structure: false
    When lyrics を読む
    Then rstrip された歌詞本文が入る。
    """
    _write_suno_override(channel_dir, genre_line="dream pop vocals", auto_lyrics_structure=False)
    patterns_path = _write_vocal_patterns(tmp_path, ["a dreamy scene"])
    _write_suno_lyrics_json(tmp_path, ["歌もの — Vocal"], lyrics="[Verse]\nla la la\n\n")

    entries = build_prompt_entries(patterns_path)

    assert entries[0]["lyrics"] == "[Verse]\nla la la"


def test_build_prompt_entries_vocal_requires_suno_lyrics_json(channel_dir, tmp_path):
    """vocal mode は `/suno-lyric` が出す suno-lyrics.json を必須にする."""
    from youtube_automation.utils.exceptions import ConfigError

    _write_suno_override(channel_dir, genre_line="dream pop vocals")
    patterns_path = _write_vocal_patterns(tmp_path, ["a dreamy scene"])

    with pytest.raises(ConfigError) as exc_info:
        build_prompt_entries(patterns_path)

    message = str(exc_info.value)
    assert "suno-lyrics.json is required for vocal mode" in message
    assert "Run /suno-lyric first" in message


def test_build_prompt_entries_vocal_prefers_suno_lyrics_json(channel_dir, tmp_path):
    """Given vocal patterns と同階層に suno-lyrics.json
    When build_prompt_entries を呼ぶ
    Then pattern 内 lyrics ではなく suno-lyrics.json の lyrics を採用する。
    """
    _write_suno_override(channel_dir, genre_line="dream pop vocals", auto_lyrics_structure=False)
    patterns_path = _write_vocal_patterns(tmp_path, ["a dreamy scene"])
    (tmp_path / "suno-lyrics.json").write_text(
        json.dumps(
            [
                {
                    "name": "歌もの — Vocal",
                    "lyrics": "[Intro]\nexternal lyric\n\n",
                    "style": None,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    entries = build_prompt_entries(patterns_path)
    md = generate(patterns_path)

    assert entries[0]["lyrics"] == "[Intro]\nexternal lyric"
    assert "[Intro]\nexternal lyric" in md
    assert "[Verse]\nla la la" not in md


def test_build_prompt_entries_vocal_merges_suno_lyrics_json_by_variation_name(channel_dir, tmp_path):
    """Given 2 scene vocal pattern と Variation 別の suno-lyrics.json
    When build_prompt_entries を呼ぶ
    Then 各 entry に同名 lyrics がマージされる。
    """
    _write_suno_override(channel_dir, genre_line="dream pop vocals", auto_lyrics_structure=False)
    patterns_path = _write_vocal_patterns(tmp_path, ["scene one", "scene two"])
    (tmp_path / "suno-lyrics.json").write_text(
        json.dumps(
            [
                {"name": "歌もの — Vocal (Variation 1)", "lyrics": "[Verse 1]\none", "style": None},
                {"name": "歌もの — Vocal (Variation 2)", "lyrics": "[Verse 1]\ntwo", "style": None},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    entries = build_prompt_entries(patterns_path)

    assert [entry["lyrics"] for entry in entries] == ["[Verse 1]\none", "[Verse 1]\ntwo"]


def test_build_prompt_entries_vocal_fails_on_duplicate_suno_lyrics_names(channel_dir, tmp_path):
    """Given suno-lyrics.json に重複 name
    When build_prompt_entries を呼ぶ
    Then どの lyrics を採用するか曖昧なので fail-loud する。
    """
    from youtube_automation.utils.exceptions import ConfigError

    _write_suno_override(channel_dir, genre_line="dream pop vocals")
    patterns_path = _write_vocal_patterns(tmp_path, ["a dreamy scene"])
    (tmp_path / "suno-lyrics.json").write_text(
        json.dumps(
            [
                {"name": "歌もの — Vocal", "lyrics": "[Verse]\none"},
                {"name": "歌もの — Vocal", "lyrics": "[Verse]\ntwo"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc_info:
        build_prompt_entries(patterns_path)

    assert "duplicated lyrics entry names" in str(exc_info.value)
    assert "歌もの — Vocal" in str(exc_info.value)


def test_build_prompt_entries_vocal_fails_when_suno_lyrics_json_missing_expected_name(channel_dir, tmp_path):
    """suno-lyrics.json が存在する場合、期待 entry name の欠落は fallback せず fail-loud."""
    from youtube_automation.utils.exceptions import ConfigError

    _write_suno_override(channel_dir, genre_line="dream pop vocals")
    patterns_path = _write_vocal_patterns(tmp_path, ["a dreamy scene"])
    (tmp_path / "suno-lyrics.json").write_text(
        json.dumps([{"name": "別名 — Wrong", "lyrics": "[Verse]\nwrong"}], ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc_info:
        build_prompt_entries(patterns_path)

    message = str(exc_info.value)
    assert "names must match prompt entry names" in message
    assert "missing: 歌もの — Vocal" in message
    assert "extra: 別名 — Wrong" in message


def test_build_prompt_entries_vocal_fails_when_multi_scene_suno_lyrics_json_is_incomplete(channel_dir, tmp_path):
    """multi scene では Variation ごとの lyrics entry が全て必要."""
    from youtube_automation.utils.exceptions import ConfigError

    _write_suno_override(channel_dir, genre_line="dream pop vocals")
    patterns_path = _write_vocal_patterns(tmp_path, ["scene one", "scene two"])
    (tmp_path / "suno-lyrics.json").write_text(
        json.dumps([{"name": "歌もの — Vocal (Variation 1)", "lyrics": "[Verse]\none"}], ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc_info:
        build_prompt_entries(patterns_path)

    assert "missing: 歌もの — Vocal (Variation 2)" in str(exc_info.value)


def test_build_prompt_entries_vocal_rejects_suno_lyrics_json_title_alias(channel_dir, tmp_path):
    """suno-lyrics.json の公開 contract は `name` 必須で、未定義 `title` alias は受け付けない."""
    from youtube_automation.utils.exceptions import ConfigError

    _write_suno_override(channel_dir, genre_line="dream pop vocals", auto_lyrics_structure=False)
    patterns_path = _write_vocal_patterns(tmp_path, ["a dreamy scene"])
    (tmp_path / "suno-lyrics.json").write_text(
        json.dumps([{"title": "歌もの — Vocal", "lyrics": "[Verse]\nfrom title"}], ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc_info:
        build_prompt_entries(patterns_path)

    assert "entry 1.name must be a non-empty string" in str(exc_info.value)


def test_build_prompt_entries_auto_vocal_requires_suno_lyrics_json(channel_dir, tmp_path):
    """mode 省略でも genre_line が vocal なら suno-lyrics.json 必須契約を適用する."""
    from youtube_automation.utils.exceptions import ConfigError

    _write_suno_override(channel_dir, genre_line="dream pop vocals")
    patterns_path = _write_minimal_patterns(tmp_path)
    data = yaml.safe_load(patterns_path.read_text(encoding="utf-8"))
    data.pop("mode", None)
    patterns_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        build_prompt_entries(patterns_path)

    assert "suno-lyrics.json is required for vocal mode" in str(exc_info.value)


def test_build_prompt_entries_auto_vocal_merges_suno_lyrics_json(channel_dir, tmp_path):
    """mode 省略 + vocal genre_line でも suno-lyrics.json を merge する."""
    _write_suno_override(channel_dir, genre_line="dream pop vocals", auto_lyrics_structure=False)
    patterns_path = _write_minimal_patterns(tmp_path)
    data = yaml.safe_load(patterns_path.read_text(encoding="utf-8"))
    data.pop("mode", None)
    patterns_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    _write_suno_lyrics_json(tmp_path, ["テスト — Test"], lyrics="[Verse]\nauto vocal")

    entries = build_prompt_entries(patterns_path)

    assert entries[0]["lyrics"] == "[Verse]\nauto vocal"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("{not json", "invalid JSON"),
        ({}, "root must be a list"),
        (["not object"], "entry 1 must be an object"),
        ([{"lyrics": "x"}], "entry 1.name must be a non-empty string"),
        ([{"name": "   ", "lyrics": "x"}], "entry 1.name must be a non-empty string"),
        ([{"name": "歌もの — Vocal", "lyrics": 123}], "entry 1.lyrics must be a string"),
    ],
)
def test_build_prompt_entries_vocal_fails_on_invalid_suno_lyrics_json_shapes(
    channel_dir,
    tmp_path,
    payload,
    expected,
):
    """外部 lyrics JSON の shape error は ConfigError として固定する."""
    from youtube_automation.utils.exceptions import ConfigError

    _write_suno_override(channel_dir, genre_line="dream pop vocals")
    patterns_path = _write_vocal_patterns(tmp_path, ["a dreamy scene"])
    raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    (tmp_path / "suno-lyrics.json").write_text(raw, encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        build_prompt_entries(patterns_path)

    assert expected in str(exc_info.value)


def test_build_prompt_entries_multiple_scenes_become_separate_variations(channel_dir, tmp_path):
    """Given 2 scene を持つ pattern
    When entries を読む
    Then scene 単位で 2 entry に分かれ、name に ` (Variation N)` が付く。
    """
    _write_suno_override(channel_dir, genre_line="dream pop vocals")
    patterns_path = _write_vocal_patterns(tmp_path, ["scene one", "scene two"])
    _write_suno_lyrics_json(
        tmp_path,
        ["歌もの — Vocal (Variation 1)", "歌もの — Vocal (Variation 2)"],
    )

    entries = build_prompt_entries(patterns_path)

    assert len(entries) == 2
    assert [e["name"] for e in entries] == [
        "歌もの — Vocal (Variation 1)",
        "歌もの — Vocal (Variation 2)",
    ]
    # 各 variation は自分の scene を style に含む
    assert "scene one" in entries[0]["style"]
    assert "scene two" in entries[1]["style"]


def test_json_style_line_shares_part_with_md_styles_line(channel_dir, tmp_path):
    """Given 同一 patterns
    When md の Styles 行と JSON entry の style を比較
    Then 同じ `<tempo>, <style>,` 部品が両方に現れる（ドリフト防止）。
    """
    genre = "lo-fi jazz, soft piano"
    _write_suno_override(channel_dir, genre_line=genre)
    patterns_path = _write_minimal_patterns(tmp_path)

    md = generate(patterns_path)
    entries = build_prompt_entries(patterns_path)

    expected_style_line = f"slow, {genre},"
    assert expected_style_line in md.splitlines()
    assert expected_style_line in entries[0]["style"]


def test_main_writes_suno_prompts_json_alongside_md(channel_dir, tmp_path, monkeypatch):
    """Given patterns ファイルパスを引数に main を実行
    When 実行後の出力ディレクトリを見る
    Then suno-prompts.md と suno-prompts.json が同ディレクトリに併出される。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano")
    patterns_path = _write_minimal_patterns(tmp_path)
    monkeypatch.setattr(sys, "argv", ["yt-generate-suno", str(patterns_path)])

    main()

    md_path = patterns_path.parent / "suno-prompts.md"
    json_path = patterns_path.parent / "suno-prompts.json"
    assert md_path.exists(), "既存の md 出力は維持されること"
    assert json_path.exists(), "suno-prompts.json が併出されること"


def test_main_json_output_is_loadable_array_of_entries(channel_dir, tmp_path, monkeypatch):
    """Given main 実行後の suno-prompts.json
    When json.loads する
    Then {name, style, lyrics} を持つ entry の配列としてロードできる。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano")
    patterns_path = _write_minimal_patterns(tmp_path)
    monkeypatch.setattr(sys, "argv", ["yt-generate-suno", str(patterns_path)])

    main()

    data = json.loads((patterns_path.parent / "suno-prompts.json").read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 1
    # #900: strict 等価から subset 検証へ緩和 (build_prompt_entries 側の relaxation と同様)。
    assert {"name", "style", "lyrics"} <= set(data[0])


def test_main_collection_dir_merges_vocal_suno_lyrics_json(channel_dir, tmp_path, monkeypatch):
    """collection directory 引数でも 20-documentation/suno-lyrics.json を JSON 出力へ merge する."""
    collection_dir = tmp_path / "collection"
    docs_dir = collection_dir / "20-documentation"
    docs_dir.mkdir(parents=True)
    _write_suno_override(channel_dir, genre_line="dream pop vocals", auto_lyrics_structure=False)
    patterns_path = _write_vocal_patterns(docs_dir, ["a dreamy scene"])
    patterns_path.rename(docs_dir / "suno-patterns.yaml")
    _write_suno_lyrics_json(docs_dir, ["歌もの — Vocal"], lyrics="[Verse]\nfrom collection dir")
    monkeypatch.setattr(sys, "argv", ["yt-generate-suno", str(collection_dir)])

    main()

    data = json.loads((docs_dir / "suno-prompts.json").read_text(encoding="utf-8"))
    assert data[0]["lyrics"] == "[Verse]\nfrom collection dir"


# ---------------------------------------------------------------------------
# tracks_per_collection モデル (インストモードのフラット曲数指定) の回帰テスト
# ---------------------------------------------------------------------------


def _write_instrumental_patterns_with_scenes(dir_: Path, scene_count: int, *, tracks_top: int | None = None) -> Path:
    """1 pattern に scene_count 個の scenes を持つインスト yaml を書き出す.

    tracks_top を渡すと yaml top-level に `tracks:` キーを併設する (コレクション上書き経路を試す)。
    """
    payload: dict = {
        "title": "Test Collection",
        "mode": "instrumental",
        "patterns": [
            {
                "name_jp": "テスト",
                "name_en": "Test",
                "tempo": "slow",
                "scenes": [f"scene description {i}" for i in range(scene_count)],
            }
        ],
    }
    if tracks_top is not None:
        payload["tracks"] = tracks_top
    path = dir_ / "patterns.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_instrumental_tracks_per_collection_match_passes(channel_dir, tmp_path):
    """Given config に tracks_per_collection=2、yaml に 1 scene
    When build_prompt_entries を呼ぶ
    Then ceil(2/2)=1 と entries=1 が一致するため通る。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano", tracks_per_collection=2)
    patterns_path = _write_instrumental_patterns_with_scenes(tmp_path, scene_count=1)

    entries = build_prompt_entries(patterns_path)

    assert len(entries) == 1


def test_instrumental_tracks_per_collection_mismatch_fails_loud(channel_dir, tmp_path):
    """Given config に tracks_per_collection=10、yaml に 1 scene
    When build_prompt_entries を呼ぶ
    Then ceil(10/2)=5 が必要だが entries=1 なので ConfigError で fail-loud する。
    """
    from youtube_automation.utils.exceptions import ConfigError

    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano", tracks_per_collection=10)
    patterns_path = _write_instrumental_patterns_with_scenes(tmp_path, scene_count=1)

    with pytest.raises(ConfigError) as exc_info:
        build_prompt_entries(patterns_path)

    msg = str(exc_info.value)
    assert "tracks_per_collection=10" in msg
    assert "5" in msg  # 期待 entry 数
    assert "1" in msg  # 実 entry 数


def test_instrumental_yaml_tracks_overrides_config(channel_dir, tmp_path):
    """Given config に tracks_per_collection=20、yaml top-level に tracks: 2、yaml に 1 scene
    When build_prompt_entries を呼ぶ
    Then yaml の tracks=2 が config を上書きし、ceil(2/2)=1 と entries=1 が一致して通る。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano", tracks_per_collection=20)
    patterns_path = _write_instrumental_patterns_with_scenes(tmp_path, scene_count=1, tracks_top=2)

    entries = build_prompt_entries(patterns_path)

    assert len(entries) == 1


def test_vocal_mode_skips_tracks_per_collection_validation(channel_dir, tmp_path):
    """Given vocal genre_line + config に tracks_per_collection=20、yaml に 1 scene
    When build_prompt_entries を呼ぶ
    Then ボーカルモードは tracks_per_collection 検証対象外なので 1 entry でも通る。
    """
    _write_suno_override(
        channel_dir,
        genre_line="lo-fi hip hop with soft male vocals",
        tracks_per_collection=20,
    )
    patterns_path = _write_instrumental_patterns_with_scenes(tmp_path, scene_count=1)
    # mode を vocal に上書きして genre_line の vocal 判定と整合させる
    data = yaml.safe_load(patterns_path.read_text(encoding="utf-8"))
    data["mode"] = "vocal"
    data["patterns"][0]["lyrics"] = "[Intro]\nla la\n"
    patterns_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    _write_suno_lyrics_json(tmp_path, ["テスト — Test"], lyrics="[Intro]\nla la")

    entries = build_prompt_entries(patterns_path)

    assert len(entries) == 1


def test_instrumental_default_tracks_per_collection_is_20(channel_dir, tmp_path):
    """Given config.default.yaml の tracks_per_collection=20 を上書きせず、yaml に 10 scenes
    When build_prompt_entries を呼ぶ
    Then default の 20 と ceil(20/2)=10 entries が一致して通る。channel override を書かなくても
         default の典型値が効くことを担保する。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano")
    patterns_path = _write_instrumental_patterns_with_scenes(tmp_path, scene_count=10)

    entries = build_prompt_entries(patterns_path)

    assert len(entries) == 10


def test_legacy_patterns_per_collection_key_is_silently_ignored(channel_dir, tmp_path):
    """Given config に旧キー patterns_per_collection=4 が残っていても (新キーは default の 20)
    When build_prompt_entries を呼ぶ
    Then コード側は新キー tracks_per_collection しか読まないため、ceil(20/2)=10 entries と
         整合させていれば旧キーの混在は無害に通る。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano", patterns_per_collection=4)
    patterns_path = _write_instrumental_patterns_with_scenes(tmp_path, scene_count=10)

    entries = build_prompt_entries(patterns_path)

    assert len(entries) == 10


# ---------------------------------------------------------------------------
# 全曲ユニーク title (entry name) 検証の回帰テスト
# ---------------------------------------------------------------------------


def _write_patterns_with_explicit_entries(dir_: Path, entries: list[dict], tracks_top: int) -> Path:
    """name_jp / name_en を明示した複数 entry の yaml を書き出す.

    重複検証テスト用に各 entry の name を任意に指定したいので独立 helper を用意する。
    """
    payload: dict = {
        "title": "Test Collection",
        "mode": "instrumental",
        "tracks": tracks_top,
        "patterns": entries,
    }
    path = dir_ / "patterns.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


def test_unique_titles_pass_when_all_entries_have_distinct_names(channel_dir, tmp_path):
    """Given 全 entry が固有の name_jp / name_en を持つ yaml
    When build_prompt_entries を呼ぶ
    Then ユニーク検証は通る。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano")
    patterns_path = _write_patterns_with_explicit_entries(
        tmp_path,
        entries=[
            {"name_jp": "屋上の静寂", "name_en": "Rooftop Silence", "tempo": "slow", "scenes": ["a quiet rooftop"]},
            {"name_jp": "朝のキッチン", "name_en": "Morning Kitchen", "tempo": "gentle", "scenes": ["a warm kitchen"]},
        ],
        tracks_top=4,
    )

    entries = build_prompt_entries(patterns_path)

    assert len(entries) == 2
    assert entries[0]["name"] != entries[1]["name"]


def test_unique_titles_fail_loud_when_two_entries_share_name(channel_dir, tmp_path):
    """Given 同一の name_jp / name_en を持つ entry が 2 つある yaml
    When build_prompt_entries を呼ぶ
    Then ConfigError で fail-loud し、重複した name が messages に含まれる。
    """
    from youtube_automation.utils.exceptions import ConfigError

    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano")
    patterns_path = _write_patterns_with_explicit_entries(
        tmp_path,
        entries=[
            {"name_jp": "屋上の静寂", "name_en": "Rooftop Silence", "tempo": "slow", "scenes": ["a quiet rooftop"]},
            {"name_jp": "屋上の静寂", "name_en": "Rooftop Silence", "tempo": "gentle", "scenes": ["another rooftop"]},
        ],
        tracks_top=4,
    )

    with pytest.raises(ConfigError) as exc_info:
        build_prompt_entries(patterns_path)

    msg = str(exc_info.value)
    assert "ユニーク" in msg
    assert "屋上の静寂 — Rooftop Silence" in msg


def test_unique_titles_treat_name_jp_and_name_en_combo_as_identity(channel_dir, tmp_path):
    """Given name_jp は同じだが name_en が異なる 2 entry
    When build_prompt_entries を呼ぶ
    Then 識別子は `{name_jp} — {name_en}` の組なので別物として通る。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano")
    patterns_path = _write_patterns_with_explicit_entries(
        tmp_path,
        entries=[
            {"name_jp": "屋上", "name_en": "Rooftop Silence", "tempo": "slow", "scenes": ["a quiet rooftop"]},
            {"name_jp": "屋上", "name_en": "Rooftop Sunset", "tempo": "gentle", "scenes": ["a warm rooftop"]},
        ],
        tracks_top=4,
    )

    entries = build_prompt_entries(patterns_path)

    assert len(entries) == 2
    assert entries[0]["name"] != entries[1]["name"]


def test_unique_titles_allow_same_pattern_name_when_variation_suffix_disambiguates(channel_dir, tmp_path):
    """Given 1 pattern 内に複数 scene を持つ vocal yaml (genre_line で auto vocal 判定)
    When build_prompt_entries を呼ぶ
    Then `(Variation N)` 付与で entry name はユニーク化されるためエラーなく通る。

    既存の multi-scene pattern (#854 由来) との後方互換を担保する。
    """
    _write_suno_override(
        channel_dir,
        genre_line="lo-fi hip hop with soft male vocals",
    )
    payload: dict = {
        "title": "Vocal Test",
        "mode": "vocal",
        "patterns": [
            {
                "name_jp": "通学路",
                "name_en": "Walking Home",
                "scenes": ["a quiet morning street", "an afternoon shortcut"],
                "lyrics": "[Intro]\nla la\n",
            }
        ],
    }
    patterns_path = tmp_path / "patterns.yaml"
    patterns_path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    _write_suno_lyrics_json(
        tmp_path,
        ["通学路 — Walking Home (Variation 1)", "通学路 — Walking Home (Variation 2)"],
    )

    entries = build_prompt_entries(patterns_path)

    assert len(entries) == 2
    assert entries[0]["name"].endswith("(Variation 1)")
    assert entries[1]["name"].endswith("(Variation 2)")


# ---------------------------------------------------------------------------
# issue #900: More Options 3 フィールド (style_influence / weirdness / exclude_styles)
# の suno-prompts.json への wire
#
# 採用方針 (plan.md A 案): JSON への反映は **channel override (config/skills/suno.yaml) に
# 明示設定されたキーのみ**。config.default.yaml 同梱の既定値 (style_influence: 50 /
# exclude_styles リスト) は JSON には載せない (= 要件2「何も足さない既存 collection は 3 キー
# ちょうど」を満たすため)。MD 出力は従来どおり merged 値 (既定 50) を表示する。
#
# 【要レビュー】product owner が B 案 (同梱既定の暗黙 auto-flow) を意図する場合、本セクションの
# テストは設計やり直しが必要 (特に backward-compat の exact-3-keys テスト)。
# ---------------------------------------------------------------------------


def test_build_prompt_entries_includes_style_influence_from_channel_override(channel_dir, tmp_path):
    """要件1: Given channel override に style_influence: 85
    When build_prompt_entries を呼ぶ
    Then entry に "style_influence": 85 (int) が含まれる。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz", style_influence=85)
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    assert entries[0]["style_influence"] == 85
    assert isinstance(entries[0]["style_influence"], int)


def test_build_prompt_entries_includes_weirdness_from_channel_override(channel_dir, tmp_path):
    """要件1: Given channel override に weirdness: 30
    When build_prompt_entries を呼ぶ
    Then entry に "weirdness": 30 (int) が含まれる。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz", weirdness=30)
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    assert entries[0]["weirdness"] == 30
    assert isinstance(entries[0]["weirdness"], int)


def test_build_prompt_entries_includes_exclude_styles_from_channel_override(channel_dir, tmp_path):
    """要件1: Given channel override に exclude_styles: "hyperpop, edm"
    When build_prompt_entries を呼ぶ
    Then entry に "exclude_styles": "hyperpop, edm" (str) が含まれる。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz", exclude_styles="hyperpop, edm")
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    assert entries[0]["exclude_styles"] == "hyperpop, edm"
    assert isinstance(entries[0]["exclude_styles"], str)


def test_build_prompt_entries_includes_all_three_advanced_fields(channel_dir, tmp_path):
    """要件6: 新規 3 フィールドを全て含む test ケース 1 件。

    Given channel override に style_influence / weirdness / exclude_styles 全て設定
    When build_prompt_entries を呼ぶ
    Then base 3 キーに加え 3 フィールドが正しい値で載る (合計 6 キーちょうど)。
    """
    _write_suno_override(
        channel_dir,
        genre_line="lo-fi jazz",
        style_influence=85,
        weirdness=30,
        exclude_styles="hyperpop, edm",
    )
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)
    entry = entries[0]

    assert {"name", "style", "lyrics"} <= set(entry)
    assert entry["style_influence"] == 85
    assert entry["weirdness"] == 30
    assert entry["exclude_styles"] == "hyperpop, edm"
    assert set(entry) == {"name", "style", "lyrics", "style_influence", "weirdness", "exclude_styles"}


def test_build_prompt_entries_includes_zero_valued_sliders(channel_dir, tmp_path):
    """境界値: Given channel override に style_influence: 0 / weirdness: 0
    When build_prompt_entries を呼ぶ
    Then 0 は falsy だが有効値なので両方とも entry に載る。

    `if value is not None` でなく `if value:` でガードすると 0 が脱落する典型バグの回帰ガード。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz", style_influence=0, weirdness=0)
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    assert entries[0]["style_influence"] == 0
    assert entries[0]["weirdness"] == 0


def test_build_prompt_entries_includes_vocal_gender_male(channel_dir, tmp_path):
    """channel override に vocal_gender: male があれば entry に wire される。

    suno-helper 拡張は entry.vocal_gender を読んで Suno UI Voice section の Male/Female ボタンを click する。
    Python → JSON → 拡張の経路を pin する。"male" / "female" / "neutral" / "auto" が拡張型契約。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz", vocal_gender="male")
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    assert entries[0]["vocal_gender"] == "male"


def test_build_prompt_entries_omits_empty_vocal_gender(channel_dir, tmp_path):
    """channel override に vocal_gender: "" (空文字) があれば JSON に出さない (skip)。

    config.default.yaml は `vocal_gender: ""` を既定値として持つ。チャンネルが明示的に空文字を上書き
    しても、拡張型契約 ("male"|"female"|"neutral"|"auto") に "" は無く、拡張側は何もしない。
    JSON に "" を載せると型契約とミスマッチするため Python 側で skip する (一貫性と冗長排除)。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz", vocal_gender="")
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    assert "vocal_gender" not in entries[0]


def test_build_prompt_entries_omits_advanced_fields_without_channel_override(channel_dir, tmp_path):
    """要件2 + A 案の核心: Given channel override が genre_line のみ (More Options 無し) の既存 collection
    When build_prompt_entries を呼ぶ
    Then name/style/lyrics の 3 キーちょうど。

    config.default.yaml の style_influence: 50 / exclude_styles リストは merged config に存在するが、
    A 案では JSON に **載せない** (channel override に明示されたキーのみ wire する)。
    この test が A 案 (明示 gating) と B 案 (既定の暗黙 auto-flow) を機械的に区別し、後方互換を pin する。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz")
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    assert set(entries[0]) == {"name", "style", "lyrics"}
    assert "style_influence" not in entries[0]
    assert "weirdness" not in entries[0]
    assert "exclude_styles" not in entries[0]


def test_build_prompt_entries_omits_advanced_fields_when_no_override_file(channel_dir, tmp_path):
    """要件2 + A 案: Given channel に suno.yaml override ファイルが無い
    When build_prompt_entries を呼ぶ
    Then name/style/lyrics の 3 キーちょうど。

    override ファイル不在 → load_channel_override は {} → default.yaml の既定 style_influence: 50 /
    exclude_styles は JSON に載らない。
    """
    # suno.yaml を書かない (channel_dir フィクスチャは config/skills ディレクトリのみ作る)
    patterns_path = _write_minimal_patterns(tmp_path)

    entries = build_prompt_entries(patterns_path)

    assert set(entries[0]) == {"name", "style", "lyrics"}


def test_md_shows_default_style_influence_but_json_omits_it(channel_dir, tmp_path):
    """A 案の MD/JSON 非対称を pin する。

    Given channel override が genre_line のみ (advanced 無し)
    When MD と JSON を生成
    Then MD は merged の Style Influence (default 50%) を表示するが、JSON entry は
         style_influence キーを持たない (既存 MD 出力は無改修)。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz")
    patterns_path = _write_minimal_patterns(tmp_path)

    md = generate(patterns_path)
    entries = build_prompt_entries(patterns_path)

    assert "| Style Influence | 50% |" in md
    assert "style_influence" not in entries[0]


def test_channel_override_style_influence_flows_to_both_md_and_json(channel_dir, tmp_path):
    """Given channel override に style_influence: 70
    When MD と JSON を生成
    Then MD は 70% を表示し、JSON entry も "style_influence": 70 を持つ (override は両方に効く)。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz", style_influence=70)
    patterns_path = _write_minimal_patterns(tmp_path)

    md = generate(patterns_path)
    entries = build_prompt_entries(patterns_path)

    assert "| Style Influence | 70% |" in md
    assert entries[0]["style_influence"] == 70


def test_advanced_fields_apply_to_every_entry_collection_scope(channel_dir, tmp_path):
    """Given multi-scene pattern + channel override の weirdness
    When build_prompt_entries を呼ぶ
    Then 全 entry に同じ weirdness が載る (3 値は collection スコープで全 entry 共通)。
    """
    _write_suno_override(channel_dir, genre_line="dream pop vocals", weirdness=40)
    patterns_path = _write_vocal_patterns(tmp_path, ["scene one", "scene two"])
    _write_suno_lyrics_json(
        tmp_path,
        ["歌もの — Vocal (Variation 1)", "歌もの — Vocal (Variation 2)"],
    )

    entries = build_prompt_entries(patterns_path)

    assert len(entries) == 2
    assert all(e["weirdness"] == 40 for e in entries)


# ---------------------------------------------------------------------------
# issue #1456: Style 自動バリエーション (entry ごとの微差付与)
#
# 契約: `style_variation.enabled` (default.yaml で true) のとき、entry の通し番号で
# pools から descriptor を決定的に割り当て Style 第 1 行末尾へ付与する。
# 先頭 entry (index 0) は base style を維持し、明示 style variant のある entry は
# override を優先して付与しない。genre_line のコアジャンルは全 entry で維持される。
# ---------------------------------------------------------------------------


def _style_first_lines(entries: list[dict]) -> list[str]:
    return [entry["style"].splitlines()[0] for entry in entries]


def _four_distinct_entries() -> list[dict]:
    return [
        {"name_jp": "屋上の静寂", "name_en": "Rooftop Silence", "tempo": "slow", "scenes": ["a quiet rooftop"]},
        {"name_jp": "朝のキッチン", "name_en": "Morning Kitchen", "tempo": "slow", "scenes": ["a warm kitchen"]},
        {"name_jp": "港の夜明け", "name_en": "Harbor Dawn", "tempo": "slow", "scenes": ["a still harbor"]},
        {"name_jp": "路地の灯り", "name_en": "Alley Glow", "tempo": "slow", "scenes": ["a narrow alley"]},
    ]


def test_default_yaml_enables_style_variation_with_pools():
    """default.yaml が style_variation を有効化し、非空の pools を持つこと (#1456 の既定動作を pin)."""
    data = yaml.safe_load(_DEFAULT_YAML.read_text(encoding="utf-8"))

    variation = data["style_variation"]
    assert variation["enabled"] is True
    pools = variation["pools"]
    assert isinstance(pools, dict) and pools
    assert all(isinstance(pool, list) and pool for pool in pools.values())


def test_style_variation_makes_entry_style_first_lines_distinct(channel_dir, tmp_path):
    """要件1: Given 複数 entry のインスト yaml (default で variation 有効)
    When build_prompt_entries を呼ぶ
    Then 各 entry の Style 第 1 行が互いに異なる文字列になる。
    """
    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano")
    patterns_path = _write_patterns_with_explicit_entries(tmp_path, entries=_four_distinct_entries(), tracks_top=8)

    entries = build_prompt_entries(patterns_path)

    first_lines = _style_first_lines(entries)
    assert len(first_lines) == 4
    assert len(set(first_lines)) == 4, f"Style 第 1 行が重複している: {first_lines!r}"


def test_style_variation_keeps_first_entry_base_style(channel_dir, tmp_path):
    """先頭 entry (通し番号 0) は descriptor なしの base style を維持する (後方互換の核心)."""
    genre = "lo-fi jazz, soft piano"
    _write_suno_override(channel_dir, genre_line=genre)
    patterns_path = _write_patterns_with_explicit_entries(tmp_path, entries=_four_distinct_entries(), tracks_top=8)

    entries = build_prompt_entries(patterns_path)

    assert _style_first_lines(entries)[0] == f"slow, {genre},"


def test_style_variation_preserves_core_genre_line_in_all_entries(channel_dir, tmp_path):
    """要件2: バリエーションは genre_line のコアジャンルを変えない (全 entry に共通プレフィックスが残る)."""
    genre = "lo-fi jazz, soft piano"
    _write_suno_override(channel_dir, genre_line=genre)
    patterns_path = _write_patterns_with_explicit_entries(tmp_path, entries=_four_distinct_entries(), tracks_top=8)

    entries = build_prompt_entries(patterns_path)

    for line in _style_first_lines(entries):
        assert line.startswith(f"slow, {genre},"), f"コアジャンルが維持されていない: {line!r}"


def test_style_variation_is_deterministic_across_runs(channel_dir, tmp_path):
    """決定的ローテーション: 同じ入力から 2 回生成しても同一の entries になる (再生成の再現性)."""
    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano")
    patterns_path = _write_patterns_with_explicit_entries(tmp_path, entries=_four_distinct_entries(), tracks_top=8)

    first = build_prompt_entries(patterns_path)
    second = build_prompt_entries(patterns_path)

    assert first == second


def test_style_variation_disabled_restores_legacy_identical_first_lines(channel_dir, tmp_path):
    """要件3: `style_variation.enabled: false` で従来動作 (全 entry 同一の Style 第 1 行) に戻る."""
    genre = "lo-fi jazz, soft piano"
    _write_suno_override(channel_dir, genre_line=genre, style_variation={"enabled": False})
    patterns_path = _write_patterns_with_explicit_entries(tmp_path, entries=_four_distinct_entries(), tracks_top=8)

    entries = build_prompt_entries(patterns_path)

    assert set(_style_first_lines(entries)) == {f"slow, {genre},"}


def test_style_variation_skips_explicit_style_variant_entries(channel_dir, tmp_path):
    """要件4: 明示 `style` variant のある entry は override を優先し descriptor を付与しない."""
    variant_genre = "ambient pad, soft synth, airy textures"
    _write_suno_override(
        channel_dir,
        genre_line="lo-fi jazz, soft piano",
        style_variants={"ambient": {"name": "ambient pad", "genre_line": variant_genre}},
    )
    entries_def = _four_distinct_entries()
    entries_def[2]["style"] = "ambient"  # 3 番目 (通し番号 2) だけ明示 variant
    patterns_path = _write_patterns_with_explicit_entries(tmp_path, entries=entries_def, tracks_top=8)

    entries = build_prompt_entries(patterns_path)

    first_lines = _style_first_lines(entries)
    # variant entry は variant genre_line そのまま (descriptor なし)
    assert first_lines[2] == f"slow, {variant_genre},"
    # variant 以外の 2 entry 目以降には descriptor が付き互いに異なる
    assert first_lines[1] != first_lines[3]
    assert len(set(first_lines)) == 4


def test_style_variation_applies_to_vocal_multi_scene_entries(channel_dir, tmp_path):
    """ボーカルモード: 同一 pattern 内の複数 scene (Variation N) にも entry 単位で微差が付く."""
    _write_suno_override(channel_dir, genre_line="dream pop vocals", auto_lyrics_structure=False)
    patterns_path = _write_vocal_patterns(tmp_path, ["scene one", "scene two"])
    _write_suno_lyrics_json(
        tmp_path,
        ["歌もの — Vocal (Variation 1)", "歌もの — Vocal (Variation 2)"],
    )

    entries = build_prompt_entries(patterns_path)

    first_lines = _style_first_lines(entries)
    assert first_lines[0] == "mid, dream pop vocals,"
    assert first_lines[1] != first_lines[0]
    assert first_lines[1].startswith("mid, dream pop vocals,")


def test_style_variation_md_and_json_share_same_style_lines(channel_dir, tmp_path):
    """md の Styles ブロックと JSON entry の style がバリエーション込みで同一部品を共有する (ドリフト防止)."""
    _write_suno_override(channel_dir, genre_line="lo-fi jazz, soft piano")
    patterns_path = _write_patterns_with_explicit_entries(tmp_path, entries=_four_distinct_entries(), tracks_top=8)

    md = generate(patterns_path)
    entries = build_prompt_entries(patterns_path)

    md_lines = md.splitlines()
    for line in _style_first_lines(entries):
        assert line in md_lines, f"JSON の Style 第 1 行が md に存在しない: {line!r}"


def test_style_variation_wraps_when_pool_is_exhausted(channel_dir, tmp_path):
    """pool が枯渇したら循環割り当てに戻る (エラーにしない).

    pools は deep-merge で axis 単位にマージされるため、default の rhythm axis は
    空リスト上書きで無効化して texture 1 語だけの pool を作る (axis 無効化の検証を兼ねる)。
    """
    _write_suno_override(
        channel_dir,
        genre_line="lo-fi jazz",
        style_variation={"enabled": True, "pools": {"texture": ["warm rounded texture"], "rhythm": []}},
    )
    patterns_path = _write_patterns_with_explicit_entries(tmp_path, entries=_four_distinct_entries()[:3], tracks_top=6)

    entries = build_prompt_entries(patterns_path)

    first_lines = _style_first_lines(entries)
    assert first_lines[0] == "slow, lo-fi jazz,"
    assert first_lines[1] == "slow, lo-fi jazz, warm rounded texture,"
    assert first_lines[2] == "slow, lo-fi jazz, warm rounded texture,"


def test_build_prompt_entries_warns_on_duplicate_full_style(channel_dir, tmp_path, capsys):
    """要件6: 全 entry の Style 文が完全一致する組があれば生成時に警告する."""
    _write_suno_override(channel_dir, genre_line="lo-fi jazz", style_variation={"enabled": False})
    patterns_path = _write_patterns_with_explicit_entries(
        tmp_path,
        entries=[
            {"name_jp": "屋上の静寂", "name_en": "Rooftop Silence", "tempo": "slow", "scenes": ["a quiet rooftop"]},
            {"name_jp": "屋上の残響", "name_en": "Rooftop Echoes", "tempo": "slow", "scenes": ["a quiet rooftop"]},
        ],
        tracks_top=4,
    )

    build_prompt_entries(patterns_path)

    captured = capsys.readouterr()
    assert "Duplicate Style text" in captured.err


def test_build_prompt_entries_no_duplicate_style_warning_when_unique(channel_dir, tmp_path, capsys):
    """バリエーション有効時、scene が異なる複数 entry では重複警告が出ない."""
    _write_suno_override(channel_dir, genre_line="lo-fi jazz")
    patterns_path = _write_patterns_with_explicit_entries(tmp_path, entries=_four_distinct_entries(), tracks_top=8)

    build_prompt_entries(patterns_path)

    captured = capsys.readouterr()
    assert "Duplicate Style text" not in captured.err


def test_main_json_output_includes_advanced_fields_when_overridden(channel_dir, tmp_path, monkeypatch):
    """Given channel override に 3 フィールド + main 実行
    When suno-prompts.json を json.loads
    Then 配信される JSON entry に 3 フィールドが含まれる (end-to-end の wire 検証)。
    """
    _write_suno_override(
        channel_dir,
        genre_line="lo-fi jazz",
        style_influence=85,
        weirdness=30,
        exclude_styles="hyperpop, edm",
    )
    patterns_path = _write_minimal_patterns(tmp_path)
    monkeypatch.setattr(sys, "argv", ["yt-generate-suno", str(patterns_path)])

    main()

    data = json.loads((patterns_path.parent / "suno-prompts.json").read_text(encoding="utf-8"))
    assert data[0]["style_influence"] == 85
    assert data[0]["weirdness"] == 30
    assert data[0]["exclude_styles"] == "hyperpop, edm"
