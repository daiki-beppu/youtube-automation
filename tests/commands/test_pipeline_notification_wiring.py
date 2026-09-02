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


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[NotificationEvent] = []

    def notify(self, event: NotificationEvent) -> bool:
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
        on_resource_diagnostics,
        on_state_sync_event,
    ):
        assert resource_probe is not None
        assert on_resource_event is not None
        on_resource_diagnostics("disk_free=1/0 bytes")
        on_state_sync_event(
            NotificationEvent(
                NotificationEventKind.NON_FAST_FORWARD_STOPPED,
                request.channel,
                request.collection,
                "state-sync",
                "rejected",
            )
        )
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
            "rejected",
        )
    ]


@pytest.mark.parametrize("stage", ["planning", "post-publish"])
def test_handoff_free_hybrid_stage_does_not_require_media_store(monkeypatch, tmp_path: Path, stage: str) -> None:
    def reject_r2_configuration():
        raise AssertionError("handoff-free stages must not resolve R2 credentials")

    def fake_run_sandwich(
        request,
        store,
        *,
        resource_probe,
        on_resource_event,
        on_resource_diagnostics,
        on_state_sync_event,
    ):
        assert request.stage == stage
        assert store is None
        assert resource_probe.inspect().r2_retained_bytes == 0
        return SandwichResult("completed", request.collection)

    monkeypatch.setattr(hybrid_runner.R2MediaStoreConfig, "from_environment", reject_r2_configuration)
    monkeypatch.setattr(hybrid_runner, "create_discord_notification_sink", RecordingSink)
    monkeypatch.setattr(hybrid_runner, "run_sandwich", fake_run_sandwich)

    result = hybrid_runner.run(
        Namespace(
            media_store="r2",
            local_store_root=None,
            channel_dir=tmp_path,
            collection_dir="collections/planning/night-rain",
            channel_slug="ambient-lab",
            collection="night-rain",
            agent="claude",
            stage=stage,
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


def test_hybrid_command_resolves_workspace_channel_from_slug(monkeypatch, tmp_path: Path) -> None:
    channel_dir = tmp_path / "channels" / "ambient-lab"
    (channel_dir / "config" / "channel").mkdir(parents=True)

    def fake_run_sandwich(
        request,
        store,
        *,
        resource_probe,
        on_resource_event,
        on_resource_diagnostics,
        on_state_sync_event,
    ):
        assert store is None
        assert request.channel_dir == channel_dir.resolve()
        assert resource_probe.channel_dir == channel_dir.resolve()
        return SandwichResult("completed", request.collection)

    monkeypatch.setattr(hybrid_runner, "create_discord_notification_sink", RecordingSink)
    monkeypatch.setattr(hybrid_runner, "run_sandwich", fake_run_sandwich)

    result = hybrid_runner.run(
        Namespace(
            media_store="r2",
            local_store_root=None,
            channel_dir=tmp_path,
            collection_dir="collections/planning/night-rain",
            channel_slug="ambient-lab",
            collection="night-rain",
            agent="claude",
            stage="planning",
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


def test_hybrid_command_rejects_unknown_workspace_channel_before_execution(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    (tmp_path / "channels" / "ambient-lab" / "config" / "channel").mkdir(parents=True)
    runner = MagicMock(side_effect=AssertionError("runner must not execute"))
    monkeypatch.setattr(hybrid_runner, "run_sandwich", runner)

    result = hybrid_runner.main(
        [
            "--channel-dir",
            str(tmp_path),
            "--channel-slug",
            "missing",
            "--collection",
            "night-rain",
            "--collection-dir",
            "collections/planning/night-rain",
            "--stage",
            "planning",
            "--prompt",
            "/wf-new --auto",
        ]
    )

    assert result == 1
    assert "--channel-slug='missing' に対応するチャンネルがありません" in capsys.readouterr().err
    runner.assert_not_called()


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


def test_upload_execution_failure_notifies_with_execution_stage(monkeypatch, tmp_path: Path) -> None:
    """execute_next_step 全体を囲む try は preflight ではなく実行系 stage を通知する。"""
    target = tmp_path / "collections" / "planning" / "night-rain"
    uploader = MagicMock()
    uploader.find_collection.return_value = target
    uploader.execute_next_step.side_effect = ConfigError("channel mismatch")
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
            "upload-execution",
        )
    ]
    uploader.execute_next_step.assert_called_once_with(target)


def test_plan_preflight_failure_notifies_with_preflight_stage(monkeypatch, tmp_path: Path) -> None:
    """--plan の fail-closed は preflight 由来なので stage も preflight を示す。"""
    target = tmp_path / "collections" / "planning" / "night-rain"
    uploader = MagicMock()
    uploader.find_collection.return_value = target
    uploader.preflight_check.side_effect = ConfigError("channel mismatch")
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
        collection_uploader.run(Namespace(config=None, daemon=False, collection="night-rain", status=False, plan=True))

    assert sink.events == [
        NotificationEvent(
            NotificationEventKind.FAIL_CLOSED_ABORTED,
            "ambient-lab",
            "night-rain",
            "upload-preflight",
        )
    ]
    uploader.preflight_check.assert_called_once_with(target)
    uploader.show_plan.assert_not_called()
    uploader.execute_next_step.assert_not_called()
