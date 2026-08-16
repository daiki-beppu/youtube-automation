from pathlib import Path

import pytest

from tests.helpers.video_description import write_video_description_pair
from youtube_automation.core.errors import DocumentRenderError, ValidationError
from youtube_automation.domains.uploads.description_document import load_description_document


def test_upload_loader_reads_only_validated_json_pair(tmp_path: Path) -> None:
    documentation = tmp_path / "20-documentation"
    documentation.mkdir()
    write_video_description_pair(documentation, tags=["focus", "rain"])

    metadata = load_description_document(tmp_path)

    assert metadata is not None
    assert metadata["title"] == "Rain Focus — Complete Collection"
    assert metadata["tags"] == ["focus", "rain"]


def test_upload_loader_rejects_legacy_markdown_instead_of_parsing_it(tmp_path: Path) -> None:
    documentation = tmp_path / "20-documentation"
    documentation.mkdir()
    (documentation / "descriptions.md").write_text("## タイトル案\n```\nlegacy\n```", encoding="utf-8")

    with pytest.raises(ValidationError, match="明示 migration"):
        load_description_document(tmp_path)


def test_upload_loader_fails_closed_when_pair_is_tampered(tmp_path: Path) -> None:
    documentation = tmp_path / "20-documentation"
    documentation.mkdir()
    source = write_video_description_pair(documentation)
    source.with_suffix(".html").write_text("tampered", encoding="utf-8")

    with pytest.raises(DocumentRenderError, match="対応していません"):
        load_description_document(tmp_path)
