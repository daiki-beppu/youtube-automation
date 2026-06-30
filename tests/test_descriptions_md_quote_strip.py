"""_descriptions_md.py のタグ quote 除去テスト (#1096).

descriptions.md 経由のタグパーサーでダブルクォートが自動除去されることを担保する。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

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

    def test_warns_with_recreate_guide_when_required_sections_missing(self, tmp_path: Path, caplog) -> None:
        """必須セクション欠落時は正規フローでの再作成ガイドを表示する."""
        doc_dir = tmp_path / "20-documentation"
        doc_dir.mkdir(parents=True)
        (doc_dir / "descriptions.md").write_text("手書きの説明文だけ", encoding="utf-8")

        mixin = DescriptionsMdMixin()
        with caplog.at_level(logging.WARNING):
            result = mixin._load_descriptions_md(tmp_path)

        messages = "\n".join(record.getMessage() for record in caplog.records)
        assert result is None
        assert "/video-description を再実行" in messages
        assert "必須セクション" in messages
        assert "## Complete Collection 概要欄" in messages

    def test_warns_with_expected_missing_and_detected_headings_when_heading_mismatches(
        self,
        tmp_path: Path,
        caplog,
    ) -> None:
        """見出し typo 時は期待値・不足値・検出値・修正例を表示する."""
        doc_dir = tmp_path / "20-documentation"
        doc_dir.mkdir(parents=True)
        (doc_dir / "descriptions.md").write_text(
            "## タイトル\n\n```\nTest Title\n```\n\n## Complete Collection 概要\n\n```\nTest description body.\n```\n",
            encoding="utf-8",
        )

        mixin = DescriptionsMdMixin()
        with caplog.at_level(logging.WARNING):
            result = mixin._load_descriptions_md(tmp_path)

        messages = "\n".join(record.getMessage() for record in caplog.records)
        assert result is None
        assert "期待する見出し（完全一致）" in messages
        assert (
            "不足/不一致の見出し:\n  - ## タイトル案\n  - ## Complete Collection 概要欄\n  - ## タグ（YouTube タグ欄）"
        ) in messages
        assert "検出した ## 見出し" in messages
        assert "## タイトル" in messages
        assert "修正例" in messages
        assert "/video-description を再実行" in messages

    def test_raises_with_recreate_guide_when_stray_description_file_exists(self, tmp_path: Path) -> None:
        """別名 description ファイル検出時も再作成ガイドを含める."""
        doc_dir = tmp_path / "20-documentation"
        doc_dir.mkdir(parents=True)
        (doc_dir / "description.txt").write_text("手書きの説明文", encoding="utf-8")

        mixin = DescriptionsMdMixin()
        with pytest.raises(RuntimeError) as excinfo:
            mixin._load_descriptions_md(tmp_path)

        message = str(excinfo.value)
        assert "descriptions.md" in message
        assert "固定" in message
        assert "/video-description を再実行" in message
