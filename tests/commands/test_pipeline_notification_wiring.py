from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from youtube_automation.application.hybrid_runner import SandwichResult
from youtube_automation.commands.system import hybrid_runner
from youtube_automation.commands.uploads import collection_uploader
from youtube_automation.core.errors import ConfigError
from youtube_automation.domains.notifications import NotificationEvent, NotificationEventKind
from youtube_automation.infrastructure.vcs.state_sync import StateSyncEvent, StateSyncEventKind


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[NotificationEvent] = []

    def send(self, event: NotificationEvent) -> bool:
        self.events.append(event)
        return True


def test_hybrid_command_connects_non_fast_forward_event_to_notification(monkeypatch, tmp_path: Path) -> None:
    sink = RecordingSink()

    def fake_run_sandwich(
        request,
        _store,
        *,
        resource_probe,
        on_resource_event,
        on_state_sync_event,
    ):
        assert resource_probe is not None
        assert on_resource_event is not None
        on_state_sync_event(StateSyncEvent(StateSyncEventKind.NON_FAST_FORWARD, tmp_path, "rejected"))
        return SandwichResult("completed", request.collection)

    monkeypatch.setattr(hybrid_runner, "create_discord_notification_sink", lambda: sink)
    monkeypatch.setattr(hybrid_runner, "run_sandwich", fake_run_sandwich)

    result = hybrid_runner.run(
        Namespace(
            media_store="local",
            local_store_root=tmp_path / "store",
            channel_dir=tmp_path,
            collection_dir="collections/planning/night-rain",
            channel_slug="ambient-lab",
            collection="night-rain",
            agent="claude",
            stage="pipeline",
            prompt="/wf-new --auto",
            commit_message="chore: state",
            input_handoff=None,
            input_destination=None,
            output_handoff=None,
            output_root=None,
            output_file=[],
            generation_cost_usd=0,
            monthly_run_count=0,
            estimated_run_minutes=60,
        )
    )

    assert result == 0
    assert sink.events == [
        NotificationEvent(
            NotificationEventKind.NON_FAST_FORWARD_STOPPED,
            "ambient-lab",
            "night-rain",
            "state-sync",
        )
    ]


@pytest.mark.parametrize(
    ("action", "expected_kind", "expected_stage"),
    [
        ("complete_collection_uploaded", NotificationEventKind.PUBLISH_COMPLETED, "youtube-publish"),
        ("complete_collection_quota_exhausted", NotificationEventKind.GUARD_EXCEEDED, "upload-quota"),
    ],
)
def test_upload_command_notifies_terminal_pipeline_result(
    monkeypatch,
    tmp_path: Path,
    action: str,
    expected_kind: NotificationEventKind,
    expected_stage: str,
) -> None:
    target = tmp_path / "collections" / "planning" / "night-rain"
    uploader = MagicMock()
    uploader.find_collection.return_value = target
    uploader.execute_next_step.return_value = {"action": action, "details": {}}
    sink = RecordingSink()
    monkeypatch.setattr(collection_uploader, "CollectionUploader", lambda **_kwargs: uploader)
    monkeypatch.setattr(collection_uploader, "create_authenticated_youtube_clients", lambda: object())
    monkeypatch.setattr(collection_uploader, "create_discord_notification_sink", lambda: sink)
    monkeypatch.setattr(
        collection_uploader,
        "load_config",
        lambda: SimpleNamespace(meta=SimpleNamespace(channel_short="ambient-lab")),
    )

    collection_uploader.run(Namespace(config=None, daemon=False, collection="night-rain", status=False, plan=False))

    assert sink.events == [NotificationEvent(expected_kind, "ambient-lab", "night-rain", expected_stage)]


def test_upload_preflight_failure_notifies_before_error_propagates(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "collections" / "planning" / "night-rain"
    uploader = MagicMock()
    uploader.find_collection.return_value = target
    uploader.ensure_upload_preflight.side_effect = ConfigError("channel mismatch")
    sink = RecordingSink()
    monkeypatch.setattr(collection_uploader, "CollectionUploader", lambda **_kwargs: uploader)
    monkeypatch.setattr(collection_uploader, "create_authenticated_youtube_clients", lambda: object())
    monkeypatch.setattr(collection_uploader, "create_discord_notification_sink", lambda: sink)
    monkeypatch.setattr(
        collection_uploader,
        "load_config",
        lambda: SimpleNamespace(meta=SimpleNamespace(channel_short="ambient-lab")),
    )

    with pytest.raises(ConfigError, match="channel mismatch"):
        collection_uploader.run(Namespace(config=None, daemon=False, collection="night-rain", status=False, plan=False))

    assert sink.events == [
        NotificationEvent(
            NotificationEventKind.FAIL_CLOSED_ABORTED,
            "ambient-lab",
            "night-rain",
            "upload-preflight",
        )
    ]
    uploader.execute_next_step.assert_not_called()
