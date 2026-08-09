from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.youtube.broadcast_recovery import RecoveryRequest
from youtube_automation.infrastructure.youtube.streaming.broadcast_recovery import (
    YouTubeBroadcastRecoveryGateway,
)


def _service() -> MagicMock:
    service = MagicMock()
    service.liveBroadcasts.return_value.list.return_value.execute.return_value = {"items": []}
    return service


def test_lists_active_broadcasts_and_parses_bound_stream() -> None:
    service = _service()
    service.liveBroadcasts.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "broadcast-1",
                "snippet": {"title": "Live"},
                "contentDetails": {"boundStreamId": "stream-1"},
            }
        ]
    }

    broadcasts = YouTubeBroadcastRecoveryGateway(service).list_active_broadcasts()

    assert broadcasts[0].bound_stream_id == "stream-1"
    service.liveBroadcasts.return_value.list.assert_called_once_with(
        part="id,snippet,contentDetails", broadcastStatus="active", mine=True, maxResults=50
    )


def test_lists_all_upcoming_pages_before_reuse_decision() -> None:
    service = _service()
    service.liveBroadcasts.return_value.list.return_value.execute.side_effect = [
        {"items": [], "nextPageToken": "page-2"},
        {
            "items": [
                {
                    "id": "broadcast-2",
                    "snippet": {"title": "Live"},
                    "contentDetails": {"boundStreamId": "stream-1"},
                }
            ]
        },
    ]

    broadcasts = YouTubeBroadcastRecoveryGateway(service).list_upcoming_broadcasts()

    assert [item.id for item in broadcasts] == ["broadcast-2"]
    assert service.liveBroadcasts.return_value.list.call_args_list[1].kwargs["pageToken"] == "page-2"


def test_get_stream_requests_no_cdn_or_ingestion_secret() -> None:
    service = _service()
    service.liveStreams.return_value.list.return_value.execute.return_value = {
        "items": [{"id": "stream-1", "status": {"streamStatus": "active"}}]
    }

    stream = YouTubeBroadcastRecoveryGateway(service).get_stream("stream-1")

    assert stream.status == "active"
    service.liveStreams.return_value.list.assert_called_once_with(part="id,status", id="stream-1")


def test_missing_stream_fails_loud() -> None:
    service = _service()
    service.liveStreams.return_value.list.return_value.execute.return_value = {"items": []}

    with pytest.raises(ValidationError, match="見つかりません"):
        YouTubeBroadcastRecoveryGateway(service).get_stream("stream-1")


def test_create_disables_monitor_stream_for_direct_live_transition() -> None:
    service = _service()
    service.liveBroadcasts.return_value.insert.return_value.execute.return_value = {
        "id": "broadcast-1",
        "snippet": {"title": "Channel live"},
        "contentDetails": {},
    }
    request = RecoveryRequest(
        stream_id="stream-1",
        title="Channel live",
        scheduled_start_time="2026-08-10T00:00:00Z",
        privacy_status="public",
    )

    YouTubeBroadcastRecoveryGateway(service).create_broadcast(request)

    service.liveBroadcasts.return_value.insert.assert_called_once_with(
        part="snippet,status,contentDetails",
        body={
            "snippet": {
                "title": "Channel live",
                "scheduledStartTime": "2026-08-10T00:00:00Z",
            },
            "status": {"privacyStatus": "public"},
            "contentDetails": {
                "monitorStream": {"enableMonitorStream": False},
                "enableAutoStart": False,
                "enableAutoStop": False,
            },
        },
    )


def test_bind_and_transition_use_existing_ids() -> None:
    service = _service()
    service.liveBroadcasts.return_value.bind.return_value.execute.return_value = {
        "id": "broadcast-1",
        "snippet": {"title": "Live"},
        "contentDetails": {"boundStreamId": "stream-1"},
    }
    service.liveBroadcasts.return_value.transition.return_value.execute.return_value = {
        "id": "broadcast-1",
        "snippet": {"title": "Live"},
        "contentDetails": {"boundStreamId": "stream-1"},
    }
    gateway = YouTubeBroadcastRecoveryGateway(service)

    gateway.bind_broadcast("broadcast-1", "stream-1")
    gateway.transition_to_live("broadcast-1")

    service.liveBroadcasts.return_value.bind.assert_called_once_with(
        part="id,snippet,contentDetails", id="broadcast-1", streamId="stream-1"
    )
    service.liveBroadcasts.return_value.transition.assert_called_once_with(
        part="id,snippet,contentDetails", id="broadcast-1", broadcastStatus="live"
    )
