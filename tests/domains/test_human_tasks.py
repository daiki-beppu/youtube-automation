from __future__ import annotations

from youtube_automation.domains.human_tasks import (
    CollectionTaskState,
    HumanTaskKind,
    build_human_task_report,
    render_human_tasks_markdown,
    render_human_tasks_summary,
)


def test_complete_distrokid_collection_without_submission_is_pending() -> None:
    report = build_human_task_report(
        "soulful-grooves",
        (
            CollectionTaskState("volume-two", "complete", None),
            CollectionTaskState("volume-one", "complete", None),
        ),
        distrokid_enabled=True,
    )

    assert [(task.kind, task.collection) for task in report.tasks] == [
        (HumanTaskKind.DISTROKID_SUBMISSION, "volume-one"),
        (HumanTaskKind.DISTROKID_SUBMISSION, "volume-two"),
    ]


def test_distrokid_submission_disappears_after_completion_is_recorded() -> None:
    report = build_human_task_report(
        "soulful-grooves",
        (CollectionTaskState("volume-one", "complete", "2026-08-16T01:02:03Z"),),
        distrokid_enabled=True,
    )

    assert report.tasks == ()
    assert "volume-one" not in render_human_tasks_markdown(report)
    assert "volume-one" not in render_human_tasks_summary(report)


def test_non_complete_or_disabled_distrokid_collection_is_not_actionable() -> None:
    states = (
        CollectionTaskState("planning", "planning", None),
        CollectionTaskState("publishing", "publishing", None),
        CollectionTaskState("complete", "complete", None),
    )

    disabled = build_human_task_report("ambient-lab", states, distrokid_enabled=False)
    enabled = build_human_task_report("ambient-lab", states[:2], distrokid_enabled=True)

    assert disabled.tasks == ()
    assert enabled.tasks == ()


def test_markdown_and_summary_are_deterministic_for_equivalent_state() -> None:
    states = (
        CollectionTaskState("z-last", "complete", None),
        CollectionTaskState("a-first", "complete", None),
    )
    first = build_human_task_report(
        "soulful-grooves",
        states,
        distrokid_enabled=True,
    )
    second = build_human_task_report(
        "soulful-grooves",
        tuple(reversed(states)),
        distrokid_enabled=True,
    )

    assert render_human_tasks_markdown(first) == render_human_tasks_markdown(second)
    assert render_human_tasks_summary(first) == render_human_tasks_summary(second)
    assert "generated_at" not in render_human_tasks_markdown(first)
