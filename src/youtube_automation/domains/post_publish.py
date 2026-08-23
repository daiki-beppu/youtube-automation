"""Post-publish completion tracking and cloud-stage verification owner."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from youtube_automation.core.errors import StateSyncError, ValidationError, WorkflowStateError
from youtube_automation.domains.collections.inventory import CollectionRecord, UnreadableWorkflowState, iter_collections
from youtube_automation.domains.collections.workflow_state import WorkflowState, read
from youtube_automation.infrastructure.filesystem import file_lock

HISTORY_NAME = "post_publish_history.json"
SCHEMA_VERSION = 1
STEPS = ("playlist-assignment", "pinned-comment", "metadata-audit")
PostPublishStep = Literal["playlist-assignment", "pinned-comment", "metadata-audit"]


@dataclass(frozen=True, slots=True)
class PostPublishDecision:
    status: Literal["run", "skip"]
    reason: str
    video_id: str
    completed_steps: tuple[PostPublishStep, ...]


@dataclass(frozen=True, slots=True)
class PostPublishReadiness:
    status: Literal["ready", "waiting"]
    collection: Path | None


def _require_collection(root: Path, collection: Path) -> Path:
    root = root.resolve()
    if collection.is_symlink():
        raise StateSyncError("post-publish collection must not be a symlink")
    resolved = collection.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise StateSyncError("post-publish collection must be below channel root") from exc
    if not resolved.is_dir():
        raise StateSyncError("post-publish collection must be a regular directory")
    return resolved


def _video_id(collection: Path) -> tuple[str, WorkflowState]:
    try:
        state = read(collection / "workflow-state.json")
        upload = state.upload
        video_id = upload.video_id if upload is not None else None
    except WorkflowStateError as exc:
        raise StateSyncError(f"post-publish workflow state is invalid: {collection.name}") from exc
    if state.phase != "complete" or state.stage != "live" or not video_id:
        raise StateSyncError("post-publish requires complete/live state with upload.video_id")
    return video_id, state


def _read_object(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise StateSyncError(f"post-publish history symlink is not allowed: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StateSyncError(f"post-publish history cannot be read: {path.name}") from exc
    if not isinstance(value, dict):
        raise StateSyncError(f"post-publish history root must be an object: {path.name}")
    return value


def _load_history(path: Path) -> dict[str, object]:
    if not path.exists() and not path.is_symlink():
        return {"schema_version": SCHEMA_VERSION, "videos": {}}
    history = _read_object(path)
    videos = history.get("videos")
    if history.get("schema_version") != SCHEMA_VERSION or not isinstance(videos, dict):
        raise StateSyncError("unsupported post-publish history schema")
    for video_id, entry in videos.items():
        if not isinstance(video_id, str) or not video_id or not isinstance(entry, dict):
            raise StateSyncError("post-publish history video entry is invalid")
        completed = entry.get("completed")
        if not isinstance(completed, dict):
            raise StateSyncError("post-publish history completed entry is invalid")
        if set(completed) - set(STEPS) or any(not isinstance(value, str) or not value for value in completed.values()):
            raise StateSyncError("post-publish history completed step is invalid")
    return history


def _step(value: str) -> PostPublishStep:
    if value not in STEPS:
        raise StateSyncError(f"unknown post-publish step: {value}")
    return value  # type: ignore[return-value]


def evaluate(root: Path, collection: Path, step: str) -> PostPublishDecision:
    root = root.resolve()
    collection = _require_collection(root, collection)
    canonical_step = _step(step)
    video_id, _ = _video_id(collection)
    history = _load_history(root / HISTORY_NAME)
    videos = history["videos"]
    assert isinstance(videos, dict)
    entry = videos.get(video_id, {"completed": {}})
    if not isinstance(entry, dict) or not isinstance(entry.get("completed"), dict):
        raise StateSyncError("post-publish history video entry is invalid")
    completed = entry["completed"]
    assert isinstance(completed, dict)
    completed_steps = tuple(_step(candidate) for candidate in STEPS if candidate in completed)
    if canonical_step in completed:
        return PostPublishDecision("skip", "already_completed", video_id, completed_steps)
    missing = [candidate for candidate in STEPS[: STEPS.index(canonical_step)] if candidate not in completed]
    if missing:
        raise StateSyncError(f"previous_steps_incomplete:{','.join(missing)}")
    return PostPublishDecision("run", "not_completed", video_id, completed_steps)


def _write_history(path: Path, history: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(history, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def mark_complete(root: Path, collection: Path, step: str) -> PostPublishDecision:
    root = root.resolve()
    collection = _require_collection(root, collection)
    history_path = root / HISTORY_NAME
    with file_lock(history_path):
        decision = evaluate(root, collection, step)
        if decision.status == "skip":
            return decision
        history = _load_history(history_path)
        videos = history["videos"]
        assert isinstance(videos, dict)
        entry = videos.setdefault(decision.video_id, {"completed": {}})
        assert isinstance(entry, dict)
        completed = entry["completed"]
        assert isinstance(completed, dict)
        completed[step] = datetime.now(UTC).isoformat()
        _write_history(history_path, history)
        return evaluate(root, collection, step)


def _pinned_history_path(root: Path) -> Path:
    config_path = root / "config" / "channel" / "pinned-comment.json"
    history_name = "pinned_comment_history.json"
    if config_path.exists() or config_path.is_symlink():
        config = _read_object(config_path)
        pinned = config.get("pinned_comment")
        if not isinstance(pinned, dict) or not isinstance(pinned.get("history_file"), str):
            raise StateSyncError("pinned comment configuration is invalid")
        history_name = pinned["history_file"]
    path = root / history_name
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise StateSyncError("pinned comment history must be below channel root") from exc
    return path


def _pinned_actual_exists(root: Path, video_id: str) -> bool:
    path = _pinned_history_path(root)
    if not path.exists() and not path.is_symlink():
        return False
    history = _read_object(path)
    posted = history.get("posted")
    return history.get("schema_version") == 1 and isinstance(posted, dict) and video_id in posted


def _all_steps_complete(root: Path, collection: Path) -> bool:
    video_id, _ = _video_id(collection)
    for step in STEPS:
        if evaluate(root, collection, step).status != "skip":
            return False
    return _pinned_actual_exists(root, video_id)


def _post_publish_readiness(
    records: tuple[CollectionRecord, ...],
    requested: str | None,
    is_complete: Callable[[Path], bool],
) -> PostPublishReadiness:
    candidates: list[tuple[str, str, Path]] = []
    for record in records:
        collection = record.directory
        if requested and collection.name != requested:
            continue
        if isinstance(record.state, UnreadableWorkflowState):
            continue
        try:
            upload = record.state.upload
            eligible = (
                record.state.phase == "complete"
                and record.state.stage == "live"
                and upload is not None
                and bool(upload.video_id)
            )
        except WorkflowStateError:
            continue
        if not eligible:
            continue
        complete = is_complete(collection)
        if not complete:
            candidates.append((record.state.created_at or "9999", collection.name, collection))
    if not candidates:
        return PostPublishReadiness("waiting", None)
    return PostPublishReadiness("ready", min(candidates)[2])


def resolve_post_publish_readiness(root: Path, requested: str | None = None) -> PostPublishReadiness:
    root = root.resolve()
    try:
        records = iter_collections(root, ("live",))
    except WorkflowStateError as exc:
        raise StateSyncError("post-publish inventory is invalid") from exc
    return _post_publish_readiness(records, requested, lambda collection: _all_steps_complete(root, collection))


def verify_post_publish_completion(root: Path, collection: Path) -> Path:
    root = root.resolve()
    collection = _require_collection(root, collection)
    video_id, _ = _video_id(collection)
    for step in STEPS:
        if evaluate(root, collection, step).status != "skip":
            raise StateSyncError(f"post-publish tracking is incomplete: {step}")
    if not _pinned_actual_exists(root, video_id):
        raise StateSyncError("pinned comment actual artifact is missing")
    return collection


def validate_post_publish_changes(repository: Path, changed: set[str]) -> None:
    allowed = {HISTORY_NAME, "pinned_comment_history.json"}
    unexpected = changed - allowed
    if unexpected:
        raise StateSyncError(f"cloud post-publish changed an unowned path: {sorted(unexpected)[0]}")


@dataclass(slots=True)
class PostPublishStagePolicy:
    """Adapter exposing post-publish semantics to the generic sandwich runner."""

    root: Path
    prompt: str
    requested: str | None = None
    media_handoff: object | None = None
    _readiness: PostPublishReadiness | None = None
    _completed: Path | None = None

    def __post_init__(self) -> None:
        if self.media_handoff is not None:
            raise ValidationError("post-publish stage は media handoff を受け付けません")

    @property
    def waiting(self) -> bool:
        return self._readiness is not None and self._readiness.status == "waiting"

    @property
    def collection_name(self) -> str | None:
        collection = self._completed or (self._readiness.collection if self._readiness else None)
        return collection.name if collection else None

    def resolve(self) -> None:
        self._readiness = resolve_post_publish_readiness(self.root, self.requested)

    def prompt_for(self) -> str:
        if self._readiness is None or self._readiness.collection is None:
            raise StateSyncError("cloud post-publish completion target is missing")
        return (
            f"{self.prompt}\n"
            f"Cloud post-publish target is collection {self._readiness.collection.name!r}. "
            "Use the cloud executor and do not select or modify any other collection."
        )

    def verify(self) -> str:
        if self._readiness is None or self._readiness.collection is None:
            raise StateSyncError("cloud post-publish completion target is missing")
        self._completed = verify_post_publish_completion(self.root, self._readiness.collection)
        return self._completed.name

    def allows(self, repository: Path, changed: set[str]) -> None:
        if self._completed is None:
            raise StateSyncError("cloud post-publish completion target is missing")
        validate_post_publish_changes(repository, changed)
