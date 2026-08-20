"""Collection directory discovery shared by loopback local servers."""

from __future__ import annotations

from pathlib import Path

from youtube_automation.core.errors import WorkflowStateError
from youtube_automation.domains.collections.workflow_state import read_or_none as read_workflow_state_or_none

COLLECTION_DIR_SUFFIX = "-collection"


def find_collection_dirs(root: Path) -> list[Path]:
    """Return direct ``*-collection`` children in deterministic name order."""
    if not root.is_dir():
        return []
    directories = (path for path in root.iterdir() if path.is_dir() and path.name.endswith(COLLECTION_DIR_SUFFIX))
    return sorted(directories, key=lambda path: path.name)


def find_suno_collection_dirs(root: Path) -> list[Path]:
    """Return planning collections that do not have a completed live sibling."""
    return [
        collection
        for collection in find_collection_dirs(root)
        if not _is_live_complete_collection(root, collection.name)
    ]


def _is_live_complete_collection(root: Path, collection_id: str) -> bool:
    if root.name != "planning" or root.parent.name != "collections":
        return False
    state = _read_workflow_state_lenient(root.parent / "live" / collection_id / "workflow-state.json")
    return state.get("phase") == "complete"


def _read_workflow_state_lenient(path: Path) -> dict[str, object]:
    try:
        state = read_workflow_state_or_none(path)
    except WorkflowStateError:
        return {}
    return state.to_dict() if state is not None else {}
