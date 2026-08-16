"""Readiness and completion contracts for the cloud planning stage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from youtube_automation.core.errors import StateSyncError, WorkflowStateError
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


def _planning_states(root: Path) -> list[tuple[Path, WorkflowState]]:
    planning = root.resolve() / "collections" / "planning"
    if not planning.exists():
        return []
    if planning.is_symlink() or not planning.is_dir():
        raise StateSyncError("collections/planning must be a regular directory")
    states: list[tuple[Path, WorkflowState]] = []
    for collection in sorted(planning.iterdir(), key=lambda path: path.name):
        if collection.is_symlink():
            raise StateSyncError(f"planning collection must not be a symlink: {collection.name}")
        if not collection.is_dir() or collection.name.startswith("_"):
            continue
        state_path = collection / "workflow-state.json"
        if not state_path.exists() and not state_path.is_symlink():
            continue
        try:
            state = read(state_path)
            phase = state.phase
        except WorkflowStateError as exc:
            raise StateSyncError(f"cloud planning state is invalid: {collection.name}") from exc
        if phase != "complete":
            states.append((collection.resolve(), state))
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

    active = _planning_states(root)
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
        active = _planning_states(root)
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
