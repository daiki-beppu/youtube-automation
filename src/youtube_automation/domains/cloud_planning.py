"""Readiness and completion contracts for the cloud planning stage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal

from youtube_automation.core.errors import StateSyncError, WorkflowStateError
from youtube_automation.domains.cloud_stage_policy import ReadinessStagePolicy
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

    relative_collection = collection.resolve().relative_to(repository.resolve())
    collection_prefix = f"{relative_collection.as_posix()}/"
    collection_parts = relative_collection.parts
    collections_index = collection_parts.index("collections")
    live_prefix = Path(*collection_parts[:collections_index], "collections", "live").as_posix() + "/"
    for path in changed:
        allowed_audit = path in {".automation-run/history.json", "data/insights.jsonl"}
        allowed_postmortem = path.startswith(live_prefix) and path.endswith("/20-documentation/postmortem.md")
        if not path.startswith(collection_prefix) and not allowed_audit and not allowed_postmortem:
            raise StateSyncError(f"cloud planning changed an unowned path: {path}")


@dataclass(slots=True)
class PlanningStagePolicy(ReadinessStagePolicy):
    """Adapter exposing planning semantics to the generic sandwich runner."""

    stage_label: ClassVar[str] = "planning"

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
