"""Generate the human task projection and deliver its operator summary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from youtube_automation.core.errors import WorkflowStateError
from youtube_automation.domains.collections.inventory import UnreadableWorkflowState, iter_collections
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
    records = iter_collections(channel_dir)
    unreadable = next(
        (
            record.state
            for record in records
            if isinstance(record.state, UnreadableWorkflowState)
            and (record.state.path.exists() or record.state.path.is_symlink())
        ),
        None,
    )
    if unreadable:
        raise WorkflowStateError(unreadable.reason)
    return tuple(
        CollectionTaskState(record.directory.name, record.state.phase, record.state.distrokid_submission_completed_at)
        for record in records
        if not isinstance(record.state, UnreadableWorkflowState)  # narrowed after the fail-loud check above
    )


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
