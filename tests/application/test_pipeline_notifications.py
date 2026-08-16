from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.application.hybrid_runner import HybridResourceEvent, HybridResourceEventKind
from youtube_automation.application.media_acceptance import (
    MediaAcceptanceEvent,
    MediaAcceptanceEventKind,
)
from youtube_automation.application.pipeline_notifications import PipelineNotificationBridge
from youtube_automation.application.suno_download_handoff import (
    SunoDownloadHandoffEvent,
    SunoDownloadHandoffEventKind,
)
from youtube_automation.domains.notifications import NotificationEvent, NotificationEventKind
from youtube_automation.infrastructure.vcs.state_sync import StateSyncEvent, StateSyncEventKind


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[NotificationEvent] = []

    def send(self, event: NotificationEvent) -> bool:
        self.events.append(event)
        return True


@pytest.mark.parametrize(
    ("kind", "stage"),
    [
        (NotificationEventKind.PUBLISH_COMPLETED, "publish"),
        (NotificationEventKind.FAIL_CLOSED_ABORTED, "upload-preflight"),
        (NotificationEventKind.GUARD_EXCEEDED, "upload-quota"),
        (NotificationEventKind.CANARY_FAILED, "monthly-canary"),
    ],
)
def test_emit_sends_pipeline_context_with_requested_typed_event(
    kind: NotificationEventKind,
    stage: str,
) -> None:
    sink = RecordingSink()
    bridge = PipelineNotificationBridge(sink)

    delivered = bridge.emit(
        kind,
        channel="ambient-lab",
        collection="night-rain",
        stage=stage,
    )

    assert delivered is True
    assert sink.events == [NotificationEvent(kind, "ambient-lab", "night-rain", stage)]


def test_state_sync_maps_non_fast_forward_to_abnormal_pipeline_event() -> None:
    sink = RecordingSink()
    bridge = PipelineNotificationBridge(sink)

    bridge.state_sync(
        StateSyncEvent(
            kind=StateSyncEventKind.NON_FAST_FORWARD,
            repository=Path("/channel"),
            message="not forwarded",
        ),
        channel="ambient-lab",
        collection="night-rain",
    )

    assert sink.events == [
        NotificationEvent(
            NotificationEventKind.NON_FAST_FORWARD_STOPPED,
            "ambient-lab",
            "night-rain",
            "state-sync",
        )
    ]


def test_suno_handoff_preserves_event_channel_and_collection() -> None:
    sink = RecordingSink()
    bridge = PipelineNotificationBridge(sink)

    bridge.suno_handoff(
        SunoDownloadHandoffEvent(
            kind=SunoDownloadHandoffEventKind.COMPLETED,
            channel="ambient-lab",
            collection="night-rain",
            manifest_key="ambient-lab/night-rain/suno-download/manifest.json",
            root_sha256="a" * 64,
        )
    )

    assert sink.events == [
        NotificationEvent(
            NotificationEventKind.HANDOFF_COMPLETED,
            "ambient-lab",
            "night-rain",
            "suno-download-handoff",
        )
    ]


def test_media_acceptance_maps_rejection_with_explicit_channel() -> None:
    sink = RecordingSink()
    bridge = PipelineNotificationBridge(sink)

    bridge.media_acceptance(
        MediaAcceptanceEvent(
            kind=MediaAcceptanceEventKind.REJECTED,
            collection="night-rain",
            issue_codes=("duration",),
            detail="too short",
        ),
        channel="ambient-lab",
    )

    assert sink.events == [
        NotificationEvent(
            NotificationEventKind.FAIL_CLOSED_ABORTED,
            "ambient-lab",
            "night-rain",
            "media-acceptance",
        )
    ]


def test_resource_guard_rejection_maps_to_guard_exceeded() -> None:
    sink = RecordingSink()
    bridge = PipelineNotificationBridge(sink)

    bridge.hybrid_resources(
        HybridResourceEvent(
            HybridResourceEventKind.REJECTED,
            "ambient-lab",
            "night-rain",
            ("disk_free",),
            "insufficient disk",
        )
    )

    assert sink.events == [
        NotificationEvent(
            NotificationEventKind.GUARD_EXCEEDED,
            "ambient-lab",
            "night-rain",
            "resource-guard",
        )
    ]
