from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.application.documents.migration import MarkdownMigrationDecision
from youtube_automation.application.documents.video_description import (
    read_video_description_metadata,
    write_video_description_document,
)
from youtube_automation.core.errors import DocumentMigrationError, DocumentRenderError, DocumentValidationError


def _document(*, quality_status: str = "pass") -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": "2026-08-16T00:00:00Z",
        "collection_id": "rain-focus",
        "title": "Rain Focus — Complete Collection",
        "description": "Opening\n\n00:00 Quiet Rain\n03:12 Deep Focus\n\n#Focus",
        "description_sections": [
            {"id": "opening", "heading": "Opening", "body": "Opening"},
            {"id": "track_list", "heading": "Track list", "body": "00:00 Quiet Rain\n03:12 Deep Focus"},
        ],
        "tracks": [
            {"position": 1, "start": "00:00", "title": "Quiet Rain"},
            {"position": 2, "start": "03:12", "title": "Deep Focus"},
        ],
        "tags": ["focus music", "rain ambience"],
        "localizations": {"ja": {"title": "雨の集中用BGM", "description": "00:00 静かな雨\n03:12 深い集中"}},
        "provenance": {"producer": "video", "source_paths": ["20-documentation/plan_proposals.json"]},
        "quality": {
            "status": quality_status,
            "checks": [
                {"id": "title-length", "status": quality_status, "message": "100 codepoints以内"},
                {"id": "localizations", "status": quality_status, "message": "全locale検証済み"},
            ],
        },
    }


def _state(path: Path) -> None:
    path.write_text(
        json.dumps({"phase": "prepared", "assets": {"thumbnail": True}, "unknown": {"keep": True}}),
        encoding="utf-8",
    )


def test_verified_description_pair_updates_state_after_reread(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/descriptions.json"
    target.parent.mkdir()
    state = tmp_path / "workflow-state.json"
    _state(state)

    result = write_video_description_document(
        target,
        state,
        _document,
        MarkdownMigrationDecision.NOT_REQUIRED,
    )

    assert result.value == "created"
    assert target.with_suffix(".html").is_file()
    assert read_video_description_metadata(target) == {
        "title": "Rain Focus — Complete Collection",
        "description": "Opening\n\n00:00 Quiet Rain\n03:12 Deep Focus\n\n#Focus",
        "tags": ["focus music", "rain ambience"],
        "localizations": {"ja": {"title": "雨の集中用BGM", "description": "00:00 静かな雨\n03:12 深い集中"}},
    }
    persisted = json.loads(state.read_text())
    assert persisted["assets"] == {"thumbnail": True, "description": True}
    assert persisted["unknown"] == {"keep": True}


@pytest.mark.parametrize("failure", ["quality", "localization"])
def test_invalid_quality_or_localization_does_not_publish_or_update_state(tmp_path: Path, failure: str) -> None:
    target = tmp_path / "20-documentation/descriptions.json"
    target.parent.mkdir()
    state = tmp_path / "workflow-state.json"
    _state(state)
    before = state.read_bytes()

    def invalid_document() -> dict[str, object]:
        document = _document(quality_status="fail" if failure == "quality" else "pass")
        if failure == "localization":
            document["localizations"] = {"ja": {"title": "", "description": "本文"}}
        return document

    error = DocumentMigrationError if failure == "quality" else DocumentValidationError
    with pytest.raises(error):
        write_video_description_document(
            target,
            state,
            invalid_document,
            MarkdownMigrationDecision.NOT_REQUIRED,
        )

    assert state.read_bytes() == before
    assert not target.exists()
    assert not target.with_suffix(".html").exists()


def test_markdown_migration_requires_explicit_yes(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/descriptions.json"
    target.parent.mkdir()
    target.with_suffix(".md").write_text("legacy description", encoding="utf-8")
    state = tmp_path / "workflow-state.json"
    _state(state)

    with pytest.raises(DocumentMigrationError, match="明示的な yes/no"):
        write_video_description_document(
            target,
            state,
            _document,
            MarkdownMigrationDecision.NOT_REQUIRED,
        )

    result = write_video_description_document(target, state, _document, MarkdownMigrationDecision.YES)
    assert result.value == "migrated"
    assert not target.with_suffix(".md").exists()


def test_reader_rejects_tampered_html_pair(tmp_path: Path) -> None:
    target = tmp_path / "20-documentation/descriptions.json"
    target.parent.mkdir()
    state = tmp_path / "workflow-state.json"
    _state(state)
    write_video_description_document(target, state, _document, MarkdownMigrationDecision.NOT_REQUIRED)
    target.with_suffix(".html").write_text("tampered", encoding="utf-8")

    with pytest.raises(DocumentRenderError, match="対応していません"):
        read_video_description_metadata(target)
