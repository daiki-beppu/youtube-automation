"""Collection directory discovery shared by loopback local servers."""

from __future__ import annotations

from pathlib import Path

from youtube_automation.core.errors import WorkflowStateError
from youtube_automation.domains.collections.inventory import CollectionRecord, UnreadableWorkflowState, iter_collections
from youtube_automation.infrastructure.filesystem import list_directory, path_is_directory

COLLECTION_DIR_SUFFIX = "-collection"


def find_collection_dirs(root: Path) -> list[Path]:
    """Return direct ``*-collection`` children in deterministic name order."""
    records = _records_for_stage_root(root)
    if records is None:
        # collection server は単独の任意 directory も公開 API として受け付ける。
        # channel stage でない legacy root だけは inventory の対象外なので、既存の
        # lenient な探索を filesystem adapter 経由で維持する。
        if not path_is_directory(root):
            return []
        return sorted(
            (
                path
                for path in list_directory(root)
                if path_is_directory(path) and path.name.endswith(COLLECTION_DIR_SUFFIX)
            ),
            key=lambda path: path.name,
        )
    return [record.directory for record in records if record.directory.name.endswith(COLLECTION_DIR_SUFFIX)]


def find_suno_collection_dirs(root: Path) -> list[Path]:
    """Return planning collections that do not have a completed live sibling."""
    completed = _completed_live_collection_ids(root)
    return [collection for collection in find_collection_dirs(root) if collection.name not in completed]


def _completed_live_collection_ids(root: Path) -> frozenset[str]:
    if root.name != "planning" or root.parent.name != "collections":
        return frozenset()
    try:
        records = iter_collections(root.parent.parent, ("live",))
    except WorkflowStateError:
        return frozenset()
    completed: set[str] = set()
    for record in records:
        if isinstance(record.state, UnreadableWorkflowState):
            continue
        try:
            if record.state.phase == "complete":
                completed.add(record.directory.name)
        except WorkflowStateError:
            continue
    return frozenset(completed)


def _records_for_stage_root(root: Path) -> tuple[CollectionRecord, ...] | None:
    if root.name not in {"planning", "live"} or root.parent.name != "collections":
        return None
    return iter_collections(root.parent.parent, (root.name,))
