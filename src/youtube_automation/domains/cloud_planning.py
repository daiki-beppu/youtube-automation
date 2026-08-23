"""Readiness and completion contracts for the cloud planning stage."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from youtube_automation.core.errors import StateSyncError, ValidationError, WorkflowStateError
from youtube_automation.domains.collections.inventory import CollectionRecord, UnreadableWorkflowState, iter_collections
from youtube_automation.domains.collections.workflow_state import WorkflowState, read

_PROMPT_FILES = {
    "suno": "suno-prompts",
    "lyria": "lyria-prompt",
    "minimax": "minimax-prompt",
}


@dataclass(frozen=True, slots=True)
class PlanningReadiness:
    status: Literal["ready", "waiting"]
    collection: Path | None


def _planning_states(records: tuple[CollectionRecord, ...]) -> list[tuple[Path, WorkflowState]]:
    states: list[tuple[Path, WorkflowState]] = []
    for record in records:
        if isinstance(record.state, UnreadableWorkflowState):
            if not record.state.path.exists() and not record.state.path.is_symlink():
                continue
            raise StateSyncError(f"cloud planning state is invalid: {record.directory.name}")
        if record.state.phase != "complete":
            states.append((record.directory, record.state))
    return states


def _sort_key(item: tuple[Path, WorkflowState]) -> tuple[str, str]:
    collection, state = item
    try:
        created_at = state.created_at
    except WorkflowStateError as exc:
        raise StateSyncError(f"cloud planning created_at is invalid: {collection.name}") from exc
    return (created_at or "9999", collection.name)


def resolve_planning_readiness(root: Path) -> PlanningReadiness:
    """Select the oldest active collection without mutating repository state."""

    try:
        active = _planning_states(iter_collections(root.resolve(), ("planning",)))
    except WorkflowStateError as exc:
        raise StateSyncError("cloud planning inventory is invalid") from exc
    if not active:
        return PlanningReadiness("ready", None)
    collection, state = min(active, key=_sort_key)
    return PlanningReadiness("ready" if state.phase == "planning" else "waiting", collection)


def _require_regular(path: Path, *, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise StateSyncError(f"cloud planning {label} must be a regular file: {path}")


def verify_planning_completion(root: Path, collection: Path | None) -> Path:
    """Verify artifact and state owners completed the selected planning stage."""

    if collection is None:
        try:
            active = _planning_states(iter_collections(root.resolve(), ("planning",)))
        except WorkflowStateError as exc:
            raise StateSyncError("cloud planning inventory is invalid") from exc
        if len(active) != 1:
            raise StateSyncError("cloud planning must create exactly one active collection")
        collection, state = active[0]
    else:
        collection = collection.resolve()
        try:
            state = read(collection / "workflow-state.json")
        except WorkflowStateError as exc:
            raise StateSyncError(f"cloud planning state is invalid: {collection.name}") from exc
    planning = state.get("planning")
    assets = state.get("assets")
    if state.phase != "prepared":
        raise StateSyncError("cloud planning must finish with phase prepared")
    if not isinstance(planning, dict) or planning.get("generated") is not True:
        raise StateSyncError("cloud planning must finalize planning.generated")
    if not isinstance(assets, dict) or assets.get("music_prompts") is not True:
        raise StateSyncError("cloud planning must finalize assets.music_prompts")
    try:
        basename = _PROMPT_FILES[state.music_engine]
    except (KeyError, WorkflowStateError) as exc:
        raise StateSyncError("cloud planning music engine is invalid") from exc
    documentation = collection / "20-documentation"
    _require_regular(documentation / "plan_proposals.json", label="planning pair")
    _require_regular(documentation / "plan_proposals.html", label="planning pair")
    _require_regular(documentation / f"{basename}.json", label="prompt pair")
    _require_regular(documentation / f"{basename}.html", label="prompt pair")
    return collection


def validate_planning_changes(repository: Path, collection: Path, changed: set[str]) -> None:
    """Restrict the planning agent to its selected collection and audit outputs."""

    relative_collection = collection.resolve().relative_to(repository.resolve()).as_posix()
    collection_prefix = f"{relative_collection}/"
    for path in changed:
        allowed_audit = path in {".automation-run/history.json", "data/insights.jsonl"}
        allowed_postmortem = path.startswith("collections/live/") and path.endswith("/20-documentation/postmortem.md")
        if not path.startswith(collection_prefix) and not allowed_audit and not allowed_postmortem:
            raise StateSyncError(f"cloud planning changed an unowned path: {path}")


@dataclass(slots=True)
class PlanningStagePolicy:
    """Adapter exposing planning semantics to the generic sandwich runner."""

    root: Path
    prompt: str
    # media_handoff は application.hybrid_runner.MediaHandoffRequest を指すが、
    # domains/ は application/ に依存できないため object のまま None 判定だけを行う。
    media_handoff: object | None = None
    _readiness: PlanningReadiness | None = field(init=False, default=None, repr=False)
    _completed: Path | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        if self.media_handoff is not None:
            raise ValidationError("planning stage は media handoff を受け付けません")

    @property
    def waiting(self) -> bool:
        return self._readiness is not None and self._readiness.status == "waiting"

    @property
    def collection_name(self) -> str | None:
        collection = self._completed or (self._readiness.collection if self._readiness else None)
        return collection.name if collection else None

    def resolve(self) -> None:
        self._readiness = resolve_planning_readiness(self.root)

    def prompt_for(self) -> str:
        return self.prompt

    def verify(self) -> str:
        if self._readiness is None:
            raise StateSyncError("cloud planning readiness is missing")
        self._completed = verify_planning_completion(self.root, self._readiness.collection)
        return self._completed.name

    def allows(self, repository: Path, changed: set[str]) -> None:
        if self._completed is None:
            raise StateSyncError("cloud planning completion target is missing")
        validate_planning_changes(repository, self._completed, changed)
