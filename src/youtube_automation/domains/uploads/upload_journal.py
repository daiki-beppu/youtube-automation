"""upload の冪等性 token を所有する journal interface。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from youtube_automation.core.adapters.media import CollectionPaths
from youtube_automation.core.errors import UploadJournalCorruptError, UploadJournalSaveError
from youtube_automation.infrastructure.filesystem import (
    JSONValue,
    file_lock,
    make_directory,
    path_exists,
    read_file_text,
    replace_file,
    write_file_text,
)


class UploadJournalOutcome(Enum):
    """journal 読み込みの明示 outcome。"""

    ABSENT = "absent"
    READY = "ready"
    CORRUPT = "corrupt"


@dataclass(frozen=True)
class UploadJournalStatus:
    outcome: UploadJournalOutcome
    status: str | None
    quarantine_path: Path | None = None


class UploadAttempt:
    """特定 upload kind の再開 token と遷移操作。"""

    def __init__(self, journal: UploadJournal, kind: str, status: UploadJournalStatus) -> None:
        self._journal = journal
        self.kind = kind
        self.status = status

    @property
    def resume_uri(self) -> str | None:
        self._ensure_usable()
        return self._journal._resume_uri(self.kind)

    def record_session(self, uri: str | None) -> None:
        """resumable session URI を保存または明示的に消去する。"""
        self._ensure_usable()
        if uri is not None and not isinstance(uri, str):
            raise TypeError("upload session URI must be a string or null")

        def mutate(record: dict[str, JSONValue]) -> None:
            if uri is None:
                record.pop("resume_session_uri", None)
            else:
                record["resume_session_uri"] = uri
            record["status"] = "in_progress"

        self._journal._mutate(self.kind, mutate)

    def complete(self, video: Mapping[str, JSONValue]) -> None:
        """upload 完了を記録し、再開 token を破棄する。"""
        self._ensure_usable()
        video_id = video.get("video_id")
        if not isinstance(video_id, str) or not video_id:
            raise TypeError("completed upload video_id must be a non-empty string")

        def mutate(record: dict[str, JSONValue]) -> None:
            record.pop("resume_session_uri", None)
            record["status"] = "completed"
            record["video_id"] = video_id
            for key in ("video_url", "upload_source"):
                value = video.get(key)
                if value is not None:
                    record[key] = value

        self._journal._mutate(self.kind, mutate)

    def fail(self, error: str) -> None:
        """upload 失敗を記録する。resume token は retry のため保持する。"""
        self._ensure_usable()
        if not isinstance(error, str) or not error:
            raise TypeError("upload failure must be a non-empty string")

        def mutate(record: dict[str, JSONValue]) -> None:
            record["status"] = "failed"
            record["error"] = error

        self._journal._mutate(self.kind, mutate)

    def _ensure_usable(self) -> None:
        if self.status.outcome is UploadJournalOutcome.CORRUPT:
            raise UploadJournalCorruptError(
                f"upload journal is corrupt and was quarantined: {self.status.quarantine_path}"
            )


class UploadJournal:
    """collection 単位で upload kind ごとの冪等性 token を永続化する。"""

    def __init__(self, collection: Path) -> None:
        self.collection = collection
        self.path = CollectionPaths(collection).tracking_path

    def begin(self, kind: str) -> UploadAttempt:
        """kind の attempt を開始する。破損は resume 時に明示 error となる。"""
        _validate_kind(kind)
        status = self.status(kind)
        if status.outcome is UploadJournalOutcome.ABSENT:
            self._mutate(kind, lambda record: record.setdefault("status", "pending"))
            status = self.status(kind)
        return UploadAttempt(self, kind, status)

    def status(self, kind: str) -> UploadJournalStatus:
        """kind の状態を、欠落・正常・破損を区別して返す。"""
        _validate_kind(kind)
        outcome, document, quarantine_path = self._load()
        if outcome is not UploadJournalOutcome.READY:
            return UploadJournalStatus(outcome, None, quarantine_path)
        record = document.get(kind)
        if record is not None and not isinstance(record, dict):
            quarantine_path = self._quarantine()
            return UploadJournalStatus(UploadJournalOutcome.CORRUPT, None, quarantine_path)
        status = record.get("status") if isinstance(record, dict) else None
        return UploadJournalStatus(outcome, status if isinstance(status, str) else None)

    def _resume_uri(self, kind: str) -> str | None:
        outcome, document, quarantine_path = self._load()
        if outcome is UploadJournalOutcome.CORRUPT:
            raise UploadJournalCorruptError(f"upload journal is corrupt and was quarantined: {quarantine_path}")
        record = document.get(kind)
        if record is not None and not isinstance(record, dict):
            quarantine_path = self._quarantine()
            raise UploadJournalCorruptError(f"upload journal is corrupt and was quarantined: {quarantine_path}")
        if not isinstance(record, dict):
            return None
        uri = record.get("resume_session_uri")
        return uri if isinstance(uri, str) else None

    def _load(self) -> tuple[UploadJournalOutcome, dict[str, JSONValue], Path | None]:
        if not path_exists(self.path):
            return UploadJournalOutcome.ABSENT, {}, None
        try:
            document = json.loads(read_file_text(self.path))
            if not isinstance(document, dict):
                raise json.JSONDecodeError("root must be an object", read_file_text(self.path), 0)
        except (json.JSONDecodeError, UnicodeDecodeError):
            quarantine_path = self._quarantine()
            return UploadJournalOutcome.CORRUPT, {}, quarantine_path
        return UploadJournalOutcome.READY, document, None

    def _quarantine(self) -> Path:
        quarantine_path = self.path.with_suffix(".json.corrupt")
        try:
            replace_file(self.path, quarantine_path)
        except OSError as exc:
            raise UploadJournalCorruptError(f"upload journal could not be quarantined: {self.path}") from exc
        return quarantine_path

    def _mutate(self, kind: str, mutate: Callable[[dict[str, JSONValue]], object]) -> None:
        with file_lock(self.path):
            outcome, document, quarantine_path = self._load()
            if outcome is UploadJournalOutcome.CORRUPT:
                raise UploadJournalCorruptError(f"upload journal is corrupt and was quarantined: {quarantine_path}")
            if outcome is UploadJournalOutcome.ABSENT:
                document = {"schema_version": 3, "collection_name": self.collection.name}
            record = document.setdefault(kind, {})
            if not isinstance(record, dict):
                raise UploadJournalCorruptError(f"upload journal kind must be an object: {kind}")
            mutate(record)
            self._save(document)

    def _save(self, document: dict[str, JSONValue]) -> None:
        make_directory(self.path.parent, parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            write_file_text(temporary, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
            replace_file(temporary, self.path)
        except (OSError, TypeError, ValueError) as exc:
            temporary.unlink(missing_ok=True)
            raise UploadJournalSaveError(f"upload journal could not be saved: {self.path}") from exc


def _validate_kind(kind: str) -> None:
    if not isinstance(kind, str) or not kind:
        raise TypeError("upload kind must be a non-empty string")


__all__ = ["UploadAttempt", "UploadJournal", "UploadJournalOutcome", "UploadJournalStatus"]
