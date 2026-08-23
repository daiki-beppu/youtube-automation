from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.application.human_tasks import generate_human_tasks
from youtube_automation.core.errors import WorkflowStateError
from youtube_automation.domains.notifications import NotificationEvent


class RecordingNotifier:
    def __init__(self) -> None:
        self.events: list[NotificationEvent] = []

    def notify(self, event: NotificationEvent) -> bool:
        self.events.append(event)
        return True


def _state(root: Path, name: str, document: dict[str, object]) -> Path:
    collection = root / "collections" / "live" / name
    collection.mkdir(parents=True)
    (collection / "workflow-state.json").write_text(json.dumps(document), encoding="utf-8")
    return collection


def test_generate_writes_fixed_markdown_and_notifies_same_pending_tasks(tmp_path: Path) -> None:
    _state(tmp_path, "pending", {"phase": "complete"})
    _state(
        tmp_path,
        "submitted",
        {
            "phase": "complete",
            "human_tasks": {"distrokid_submission": {"completed_at": "2026-08-16T01:02:03Z"}},
        },
    )
    notifier = RecordingNotifier()

    first = generate_human_tasks(
        tmp_path,
        channel="soulful-grooves",
        distrokid_enabled=True,
        notifier=notifier,
    )
    before = first.path.read_bytes()
    second = generate_human_tasks(
        tmp_path,
        channel="soulful-grooves",
        distrokid_enabled=True,
        notifier=notifier,
    )

    assert first.path == tmp_path / "human-tasks.md"
    assert second.path.read_bytes() == before
    assert "pending" in before.decode()
    assert "submitted" not in before.decode()
    assert [event.collection for event in notifier.events] == ["pending", "pending"]


def test_invalid_state_does_not_overwrite_existing_human_tasks(tmp_path: Path) -> None:
    collection = tmp_path / "collections" / "live" / "broken"
    collection.mkdir(parents=True)
    (collection / "workflow-state.json").write_text("{broken", encoding="utf-8")
    destination = tmp_path / "human-tasks.md"
    destination.write_text("keep\n", encoding="utf-8")

    with pytest.raises(WorkflowStateError):
        generate_human_tasks(
            tmp_path,
            channel="soulful-grooves",
            distrokid_enabled=True,
            notifier=RecordingNotifier(),
        )

    assert destination.read_text(encoding="utf-8") == "keep\n"


def test_missing_state_is_skipped_without_hiding_valid_human_tasks(tmp_path: Path) -> None:
    (tmp_path / "collections" / "planning" / "initializing").mkdir(parents=True)
    _state(tmp_path, "pending", {"phase": "complete"})
    notifier = RecordingNotifier()

    result = generate_human_tasks(
        tmp_path,
        channel="soulful-grooves",
        distrokid_enabled=True,
        notifier=notifier,
    )

    assert [task.collection for task in result.report.tasks] == ["pending"]


def test_recording_submission_removes_task_from_file_and_next_discord_summary(tmp_path: Path) -> None:
    collection = _state(tmp_path, "volume-one", {"phase": "complete"})
    notifier = RecordingNotifier()
    generate_human_tasks(
        tmp_path,
        channel="soulful-grooves",
        distrokid_enabled=True,
        notifier=notifier,
    )
    (collection / "workflow-state.json").write_text(
        json.dumps(
            {
                "phase": "complete",
                "human_tasks": {"distrokid_submission": {"completed_at": "2026-08-16T01:02:03Z"}},
            }
        ),
        encoding="utf-8",
    )

    result = generate_human_tasks(
        tmp_path,
        channel="soulful-grooves",
        distrokid_enabled=True,
        notifier=notifier,
    )

    assert "volume-one" not in result.path.read_text(encoding="utf-8")
    assert notifier.events[0].collection == "volume-one"
    assert notifier.events[1].collection == "all"
