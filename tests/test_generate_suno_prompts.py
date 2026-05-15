"""generate_suno_prompts CLI / generate() の挙動テスト.

issue #128 で `duration_prompt` を完全削除したため、その回帰防止テストを含む。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from youtube_automation.scripts.generate_suno_prompts import generate, main
from youtube_automation.utils import skill_config

# `_skills/<skill>/config.default.yaml` の解決元になる editable install のソースツリー
_DEFAULT_YAML = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "suno" / "config.default.yaml"
_SKILL_MD = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "suno" / "SKILL.md"


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
