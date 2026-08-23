"""Provider-neutral human task derivation from canonical workflow state."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.collections.workflow_state import Phase

_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class HumanTaskKind(StrEnum):
    DISTROKID_SUBMISSION = "distrokid_submission"


@dataclass(frozen=True, slots=True)
class CollectionTaskState:
    collection: str
    phase: Phase | None
    distrokid_submission_completed_at: str | None


@dataclass(frozen=True, slots=True)
class HumanTask:
    kind: HumanTaskKind
    collection: str
    phase: Phase


@dataclass(frozen=True, slots=True)
class HumanTaskReport:
    channel: str
    tasks: tuple[HumanTask, ...]


def _validate_identifier(value: str, *, label: str) -> None:
    if _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ValidationError(f"{label} identifier が不正です: {value!r}")


def build_human_task_report(
    channel: str,
    states: tuple[CollectionTaskState, ...],
    *,
    distrokid_enabled: bool,
) -> HumanTaskReport:
    """Derive an ordered report without clocks, filesystem state, or side effects."""
    _validate_identifier(channel, label="channel")
    for state in states:
        _validate_identifier(state.collection, label="collection")
    tasks = (
        tuple(
            HumanTask(HumanTaskKind.DISTROKID_SUBMISSION, state.collection, "complete")
            for state in sorted(states, key=lambda item: item.collection)
            if state.phase == "complete" and state.distrokid_submission_completed_at is None
        )
        if distrokid_enabled
        else ()
    )
    return HumanTaskReport(channel, tasks)


def render_human_tasks_markdown(report: HumanTaskReport) -> str:
    lines = [
        "# Human Tasks",
        "",
        "このファイルは canonical workflow state から決定的に生成されます。直接編集しないでください。",
        "",
    ]
    if not report.tasks:
        lines.extend(("現在、対応が必要な人手作業はありません。", ""))
        return "\n".join(lines)
    lines.extend((f"## Pending ({len(report.tasks)})", ""))
    for task in report.tasks:
        lines.extend(
            (
                f"- [ ] DistroKid submission: `{task.collection}`",
                f"  - 完了後: `uv run yt-workflow-state --collection {task.collection} record-distrokid-submission`",
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_human_tasks_summary(report: HumanTaskReport) -> str:
    lines = (
        "[ACTION] YouTube automation human tasks",
        f"channel: {report.channel}",
        f"pending: {len(report.tasks)}",
    )
    task_lines = tuple(f"- {task.kind.value}: {task.collection} (phase={task.phase})" for task in report.tasks)
    return "\n".join((*lines, *task_lines))
