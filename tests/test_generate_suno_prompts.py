"""generate_suno_prompts CLI / generate() の挙動テスト."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from youtube_automation.scripts.generate_suno_prompts import generate, main
from youtube_automation.utils import skill_config

# `_skills/<skill>/config.default.yaml` の解決元になる editable install のソースツリー
_DEFAULT_YAML = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "suno" / "config.default.yaml"
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
    """1 パターン × 1 シーンの最小 suno-patterns.yaml を作る."""
    path = dir_ / "patterns.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "title": "Test Collection",
                "mode": "instrumental",
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
    """SKILL.md から duration_prompt の参照と V5 で長さが効くという誤記が消えていること."""
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

    変更前: 「V5 では Styles に時間指定プロンプトが反映されるようになった」と誤記。
    変更後: 「V5 では Styles で実楽曲長を制御できない / 短い場合は Extend で延長」へ。
    """
    text = _SKILL_MD.read_text(encoding="utf-8")

    # Extend による延長が長さ調整の手段として案内されていること
    assert "Extend" in text, "SKILL.md に Extend (Suno の延長機能) の記述が無い。曲が短いときの対処として明記すること。"

    # 旧誤記が削除されていること: V5 で Styles 経由の時間指定が効くという表現
    forbidden_phrases = (
        "Styles に時間指定プロンプトが反映",
        "Styles での時間指定を優先",
    )
    for phrase in forbidden_phrases:
        assert phrase not in text, (
            f"SKILL.md に旧誤記 (`{phrase}`) が残っている。"
            "Suno V5 では Styles 経由で楽曲長を制御できないため、"
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
# issue #586: 英語歌詞の style reference / Codex 経由生成
# ---------------------------------------------------------------------------


def test_default_yaml_defines_lyrics_style_reference_and_generation_provider():
    """Given suno skill の default config
    When lyrics 関連設定を読む
    Then style reference と provider 切替の初期値が定義されている。
    """
    data = yaml.safe_load(_DEFAULT_YAML.read_text(encoding="utf-8"))

    lyrics_guidelines = data["lyrics_guidelines"]
    assert lyrics_guidelines["style_reference"] == []

    lyrics_generation = data["lyrics_generation"]
    assert lyrics_generation["provider"] == "claude"
    assert set(lyrics_generation) == {"provider"}


def test_skill_md_describes_style_reference_as_style_only_input():
    """Given /suno の歌詞生成手順
    When style_reference の説明を読む
    Then 参考歌詞を文体抽出だけに使い、複製しない契約がある。
    """
    text = _SKILL_MD.read_text(encoding="utf-8")

    assert "lyrics_guidelines.style_reference" in text
    assert "style_reference" in text
    assert "verbatim" in text.lower() or "そのまま" in text
    assert "copy" in text.lower() or "コピペ" in text or "複製" in text


def test_skill_md_describes_codex_provider_without_openai_api_direct_call():
    """Given /suno の provider 切替手順
    When Codex 経由の説明を読む
    Then config provider、wrapper、ログイン確認が導線として揃っている。
    """
    text = _SKILL_MD.read_text(encoding="utf-8")

    assert "lyrics_generation.provider" in text
    assert "codex-lyrics.sh" in text
    assert "codex login status" in text
    assert "ChatGPT API" in text
    assert "直叩き" in text or "直接" in text


def test_skill_md_includes_native_english_lyrics_quality_guards():
    """Given /suno の英語歌詞生成ルール
    When 品質ガードを読む
    Then 意味反転語と benchmark 由来の英語歌詞スタイルが明示されている。
    """
    text = _SKILL_MD.read_text(encoding="utf-8")

    assert "downfall" in text
    assert "観察日記" in text
    assert "loose rhyme" in text or "ルーズ韻" in text
    assert "mantra" in text.lower() or "マントラ" in text


def test_channel_setup_rules_list_suno_lyrics_override_keys():
    text = _CONFIG_RULES_MD.read_text(encoding="utf-8")

    assert "lyrics_guidelines.style_reference" in text
    assert "lyrics_generation.provider" in text
    assert "config/skills/suno.yaml" in text


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
