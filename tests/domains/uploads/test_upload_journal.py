"""UploadJournal の永続化・破損・失敗契約。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.core.errors import UploadJournalCorruptError, UploadJournalSaveError
from youtube_automation.domains.uploads import upload_journal
from youtube_automation.domains.uploads.upload_journal import UploadJournal, UploadJournalOutcome


@pytest.mark.parametrize("kind", ["complete_collection", "short:1"])
def test_attempt_records_resume_completion_and_failure(tmp_path: Path, kind: str) -> None:
    journal = UploadJournal(tmp_path / "collection")
    attempt = journal.begin(kind)

    assert attempt.status.outcome is UploadJournalOutcome.READY
    assert attempt.resume_uri is None

    attempt.record_session("https://upload.example/session")
    assert journal.begin(kind).resume_uri == "https://upload.example/session"

    attempt.fail("quota exhausted")
    assert journal.status(kind).status == "failed"
    assert journal.begin(kind).resume_uri == "https://upload.example/session"

    attempt.complete({"video_id": "video-123", "video_url": "https://youtu.be/video-123"})
    assert journal.status(kind).status == "completed"
    assert journal.begin(kind).resume_uri is None


def test_each_write_reloads_and_preserves_concurrent_fields(tmp_path: Path) -> None:
    journal = UploadJournal(tmp_path / "collection")
    attempt = journal.begin("complete_collection")
    document = json.loads(journal.path.read_text(encoding="utf-8"))
    document["concurrent_writer"] = {"keep": True}
    journal.path.write_text(json.dumps(document), encoding="utf-8")

    attempt.record_session("https://upload.example/session")

    persisted = json.loads(journal.path.read_text(encoding="utf-8"))
    assert persisted["concurrent_writer"] == {"keep": True}


def test_explicit_session_clear_removes_only_the_resume_token(tmp_path: Path) -> None:
    journal = UploadJournal(tmp_path / "collection")
    attempt = journal.begin("complete_collection")
    attempt.record_session("https://upload.example/session")
    attempt.fail("retry later")

    attempt.record_session(None)

    assert attempt.resume_uri is None
    assert journal.status(attempt.kind).status == "in_progress"
    persisted = json.loads(journal.path.read_text())[attempt.kind]
    assert persisted["journal_error"] == "retry later"


def test_completion_ignores_absent_optional_metadata_and_preserves_other_fields(tmp_path: Path) -> None:
    journal = UploadJournal(tmp_path / "collection")
    attempt = journal.begin("complete_collection")
    attempt.complete({"video_id": "first", "video_url": "https://youtu.be/first", "upload_source": "existing"})
    attempt.record_session("https://upload.example/session")

    attempt.complete({"video_id": "second", "video_url": None})

    persisted = json.loads(journal.path.read_text())[attempt.kind]
    assert persisted["video_id"] == "second"
    assert persisted["video_url"] == "https://youtu.be/first"
    assert persisted["upload_source"] == "existing"
    assert persisted["journal_status"] == "completed"
    assert "resume_session_uri" not in persisted


@pytest.mark.parametrize(("method", "value"), [("record_session", 123), ("complete", {}), ("fail", "")])
def test_invalid_transition_does_not_write(tmp_path: Path, method: str, value: object) -> None:
    journal = UploadJournal(tmp_path / "collection")
    attempt = journal.begin("complete_collection")
    before = journal.path.read_bytes()

    with pytest.raises(TypeError):
        getattr(attempt, method)(value)

    assert journal.path.read_bytes() == before


def test_corrupt_journal_is_quarantined_and_never_looks_absent(tmp_path: Path) -> None:
    journal = UploadJournal(tmp_path / "collection")
    journal.path.parent.mkdir(parents=True)
    journal.path.write_text("{broken", encoding="utf-8")

    attempt = journal.begin("complete_collection")

    assert attempt.status.outcome is UploadJournalOutcome.CORRUPT
    assert attempt.status.quarantine_path is not None
    assert attempt.status.quarantine_path.is_file()
    with pytest.raises(UploadJournalCorruptError):
        _ = attempt.resume_uri
    with pytest.raises(UploadJournalCorruptError):
        attempt.record_session("https://upload.example/new")
    assert not journal.path.exists()


def test_malformed_kind_record_is_corrupt_not_an_empty_attempt(tmp_path: Path) -> None:
    journal = UploadJournal(tmp_path / "collection")
    journal.path.parent.mkdir(parents=True)
    journal.path.write_text('{"complete_collection":"broken"}', encoding="utf-8")

    attempt = journal.begin("complete_collection")

    assert attempt.status.outcome is UploadJournalOutcome.CORRUPT
    with pytest.raises(UploadJournalCorruptError):
        _ = attempt.resume_uri


def test_save_failure_is_not_silenced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    journal = UploadJournal(tmp_path / "collection")

    def fail_write(_path: Path, _text: str, *, encoding: str = "utf-8") -> None:
        raise OSError("disk full")

    monkeypatch.setattr(upload_journal, "write_file_text", fail_write)

    with pytest.raises(UploadJournalSaveError) as exc_info:
        journal.begin("complete_collection")

    assert isinstance(exc_info.value.__cause__, OSError)
