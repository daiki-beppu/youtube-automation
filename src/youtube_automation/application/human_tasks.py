"""Generate the human task projection and deliver its operator summary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from youtube_automation.core.errors import WorkflowStateError
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.domains.human_tasks import (
    CollectionTaskState,
    HumanTaskNotifier,
    HumanTaskReport,
    build_human_task_report,
    render_human_tasks_markdown,
)
from youtube_automation.infrastructure.filesystem import write_text_files_transactionally

HUMAN_TASKS_FILENAME = "human-tasks.md"


@dataclass(frozen=True, slots=True)
class HumanTasksGenerationResult:
    path: Path
    report: HumanTaskReport
    notification_delivered: bool


def _collection_states(channel_dir: Path) -> tuple[CollectionTaskState, ...]:
    collections_dir = channel_dir / "collections"
    if collections_dir.is_symlink():
        raise WorkflowStateError(f"collections directory に symlink は使えません: {collections_dir}")
    if not collections_dir.exists():
        return ()
    if not collections_dir.is_dir():
        raise WorkflowStateError(f"collections directory が不正です: {collections_dir}")
    discovered: list[CollectionTaskState] = []
    names: set[str] = set()
    for area_name in ("planning", "live"):
        area = collections_dir / area_name
        if not area.exists():
            continue
        if area.is_symlink() or not area.is_dir():
            raise WorkflowStateError(f"collection area が不正です: {area}")
        for collection in sorted(area.iterdir(), key=lambda path: path.name):
            if collection.is_symlink():
                raise WorkflowStateError(f"collection に symlink は使えません: {collection}")
            if not collection.is_dir():
                continue
            state_path = collection / "workflow-state.json"
            if not state_path.exists():
                continue
            if state_path.is_symlink() or not state_path.is_file():
                raise WorkflowStateError(f"workflow-state.json が不正です: {state_path}")
            if collection.name in names:
                raise WorkflowStateError(f"collection identifier が重複しています: {collection.name}")
            state = read_workflow_state(state_path)
            discovered.append(
                CollectionTaskState(
                    collection.name,
                    state.phase,
                    state.distrokid_submission_completed_at,
                )
            )
            names.add(collection.name)
    return tuple(discovered)


def generate_human_tasks(
    channel_dir: Path,
    *,
    channel: str,
    distrokid_enabled: bool,
    notifier: HumanTaskNotifier,
) -> HumanTasksGenerationResult:
    root = channel_dir.resolve()
    states = _collection_states(root) if distrokid_enabled else ()
    report = build_human_task_report(channel, states, distrokid_enabled=distrokid_enabled)
    destination = root / HUMAN_TASKS_FILENAME
    write_text_files_transactionally({destination: render_human_tasks_markdown(report)})
    delivered = notifier.send_human_tasks(report)
    return HumanTasksGenerationResult(destination, report, delivered)
