from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.core.errors import DocumentRenderError, DocumentValidationError
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents import publishing


def _weekly_document() -> dict[str, object]:
    return {
        "schema_version": 1,
        "entries": [
            {
                "week_start": "2026-08-16",
                "axes": [{"key": "rain", "label": "Rain", "votes": 3}],
                "top_axis": "rain",
            }
        ],
    }


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_json_document_publishes_same_basename_html_atomically_and_deterministically(tmp_path: Path) -> None:
    source = tmp_path / "weekly-vote-log.json"
    _write_json(source, _weekly_document())

    first = publishing.publish_json_document(source, RepositorySchema.WEEKLY_VOTE_LOG)
    first_bytes = first.read_bytes()
    second = publishing.publish_json_document(source, RepositorySchema.WEEKLY_VOTE_LOG)

    assert first == source.with_suffix(".html")
    assert second.read_bytes() == first_bytes
    assert not list(tmp_path.glob(".weekly-vote-log.html.*.tmp"))


def test_read_published_json_document_returns_validated_json_only(tmp_path: Path) -> None:
    source = tmp_path / "weekly-vote-log.json"
    document = _weekly_document()
    _write_json(source, document)
    publishing.publish_json_document(source, RepositorySchema.WEEKLY_VOTE_LOG)

    assert publishing.read_published_json_document(source, RepositorySchema.WEEKLY_VOTE_LOG) == document


def test_read_published_json_document_rejects_mismatched_html(tmp_path: Path) -> None:
    source = tmp_path / "weekly-vote-log.json"
    _write_json(source, _weekly_document())
    html = publishing.publish_json_document(source, RepositorySchema.WEEKLY_VOTE_LOG)
    html.write_text("stale", encoding="utf-8")

    with pytest.raises(DocumentRenderError, match="対応していません"):
        publishing.read_published_json_document(source, RepositorySchema.WEEKLY_VOTE_LOG)


def test_schema_failure_preserves_existing_html(tmp_path: Path) -> None:
    source = tmp_path / "weekly-vote-log.json"
    target = source.with_suffix(".html")
    target.write_bytes(b"previous")
    _write_json(source, {"entries": []})

    with pytest.raises(DocumentValidationError):
        publishing.publish_json_document(source, RepositorySchema.WEEKLY_VOTE_LOG)

    assert target.read_bytes() == b"previous"


def test_temporary_html_validation_failure_preserves_existing_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "weekly-vote-log.json"
    target = source.with_suffix(".html")
    target.write_bytes(b"previous")
    _write_json(source, _weekly_document())

    def fail_validation(_html: str) -> None:
        raise DocumentRenderError("temporary HTML validation failed")

    monkeypatch.setattr(publishing, "validate_generated_html", fail_validation)

    with pytest.raises(DocumentRenderError, match="temporary HTML"):
        publishing.publish_json_document(source, RepositorySchema.WEEKLY_VOTE_LOG)

    assert target.read_bytes() == b"previous"
    assert not list(tmp_path.glob(".weekly-vote-log.html.*.tmp"))


def test_replace_failure_preserves_existing_html_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "weekly-vote-log.json"
    target = source.with_suffix(".html")
    target.write_bytes(b"previous")
    _write_json(source, _weekly_document())

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(publishing.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        publishing.publish_json_document(source, RepositorySchema.WEEKLY_VOTE_LOG)

    assert target.read_bytes() == b"previous"
    assert not list(tmp_path.glob(".weekly-vote-log.html.*.tmp"))


def test_publisher_fsyncs_temporary_before_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "weekly-vote-log.json"
    _write_json(source, _weekly_document())
    fsynced: list[int] = []
    real_fsync = publishing.os.fsync

    def record_fsync(descriptor: int) -> None:
        fsynced.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(publishing.os, "fsync", record_fsync)

    publishing.publish_json_document(source, RepositorySchema.WEEKLY_VOTE_LOG)

    assert len(fsynced) == 1
