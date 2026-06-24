"""_descriptions_md.py のタグ quote 除去テスト (#1096).

descriptions.md 経由のタグパーサーでダブルクォートが自動除去されることを担保する。
"""

from __future__ import annotations

from pathlib import Path

from youtube_automation.agents._descriptions_md import DescriptionsMdMixin


def _write_descriptions_md(collection_dir: Path, tags_line: str) -> None:
    """テスト用の descriptions.md を所定パスに作成する."""
    doc_dir = collection_dir / "20-documentation"
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "descriptions.md").write_text(
        f"## タイトル案\n\n```\nTest Title\n```\n\n"
        f"## Complete Collection 概要欄\n\n```\nTest description body.\n```\n\n"
        f"## タグ（YouTube タグ欄）\n\n```\n{tags_line}\n```\n",
        encoding="utf-8",
    )


class TestDescriptionsMdQuoteStrip:
    """_load_descriptions_md がタグのダブルクォートを除去する."""

    def test_strips_double_quotes_from_comma_separated_tags(self, tmp_path: Path) -> None:
        """カンマ区切りのクォート付きタグから引用符を除去する."""
        _write_descriptions_md(tmp_path, '"lofi beats", "jazz", "study music"')
        mixin = DescriptionsMdMixin()
        result = mixin._load_descriptions_md(tmp_path)
        assert result is not None
        assert result["tags"] == ["lofi beats", "jazz", "study music"]

    def test_strips_double_quotes_from_newline_separated_tags(self, tmp_path: Path) -> None:
        """改行区切りのクォート付きタグから引用符を除去する."""
        _write_descriptions_md(tmp_path, '"lofi beats"\n"jazz"\n"study music"')
        mixin = DescriptionsMdMixin()
        result = mixin._load_descriptions_md(tmp_path)
        assert result is not None
        assert result["tags"] == ["lofi beats", "jazz", "study music"]

    def test_handles_mixed_quoted_and_unquoted_tags(self, tmp_path: Path) -> None:
        """クォート有無が混在するタグでも正しく処理する."""
        _write_descriptions_md(tmp_path, '"lofi beats", jazz, "study music"')
        mixin = DescriptionsMdMixin()
        result = mixin._load_descriptions_md(tmp_path)
        assert result is not None
        assert result["tags"] == ["lofi beats", "jazz", "study music"]

    def test_handles_unquoted_tags_unchanged(self, tmp_path: Path) -> None:
        """クォートなしタグはそのまま通過する."""
        _write_descriptions_md(tmp_path, "lofi beats, jazz, study music")
        mixin = DescriptionsMdMixin()
        result = mixin._load_descriptions_md(tmp_path)
        assert result is not None
        assert result["tags"] == ["lofi beats", "jazz", "study music"]
