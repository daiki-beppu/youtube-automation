"""Translate pipeline-owned events into provider-neutral notifications."""

from __future__ import annotations

from typing import assert_never

from youtube_automation.application.hybrid_runner import HybridResourceEvent, HybridResourceEventKind
from youtube_automation.application.media_acceptance import (
    MediaAcceptanceEvent,
    MediaAcceptanceEventKind,
)
from youtube_automation.application.suno_download_handoff import (
    SunoDownloadHandoffEvent,
    SunoDownloadHandoffEventKind,
)
from youtube_automation.domains.notifications import (
    NotificationEvent,
    NotificationEventKind,
    NotificationSink,
)
from youtube_automation.infrastructure.vcs.state_sync import StateSyncEvent, StateSyncEventKind


class PipelineNotificationBridge:
    """Keep pipeline event ownership separate from delivery providers."""

    def __init__(self, sink: NotificationSink) -> None:
        self._sink = sink

    def emit(
        self,
        kind: NotificationEventKind,
        *,
        channel: str,
        collection: str,
        stage: str,
    ) -> bool:
        return self._sink.send(NotificationEvent(kind, channel, collection, stage))

    def state_sync(
        self,
        event: StateSyncEvent,
        *,
        channel: str,
        collection: str,
    ) -> bool:
        if event.kind is StateSyncEventKind.NON_FAST_FORWARD:
            return self.emit(
                NotificationEventKind.NON_FAST_FORWARD_STOPPED,
                channel=channel,
                collection=collection,
                stage="state-sync",
            )
        assert_never(event.kind)

    def suno_handoff(self, event: SunoDownloadHandoffEvent) -> bool:
        if event.kind is SunoDownloadHandoffEventKind.COMPLETED:
            return self.emit(
                NotificationEventKind.HANDOFF_COMPLETED,
                channel=event.channel,
                collection=event.collection,
                stage="suno-download-handoff",
            )
        assert_never(event.kind)

    def media_acceptance(
        self,
        event: MediaAcceptanceEvent,
        *,
        channel: str,
    ) -> bool:
        if event.kind is MediaAcceptanceEventKind.REJECTED:
            return self.emit(
                NotificationEventKind.FAIL_CLOSED_ABORTED,
                channel=channel,
                collection=event.collection,
                stage="media-acceptance",
            )
        assert_never(event.kind)

    def hybrid_resources(self, event: HybridResourceEvent) -> bool | None:
        if event.kind is HybridResourceEventKind.REJECTED:
            return self.emit(
                NotificationEventKind.GUARD_EXCEEDED,
                channel=event.channel,
                collection=event.collection,
                stage="resource-guard",
            )
        if event.kind is HybridResourceEventKind.OBSERVED:
            return None
        assert_never(event.kind)
