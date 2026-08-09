"""Google YouTube Live Streaming API adapter for broadcast recovery."""

from __future__ import annotations

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.youtube.broadcast_recovery import Broadcast, RecoveryRequest, Stream
from youtube_automation.infrastructure.google.youtube import execute_youtube_request

_BROADCAST_PARTS = "id,snippet,contentDetails"


class YouTubeBroadcastRecoveryGateway:
    def __init__(self, service) -> None:
        self._service = service

    def _list_broadcasts(self, status: str) -> list[Broadcast]:
        broadcasts: list[Broadcast] = []
        page_token: str | None = None
        while True:
            params: dict[str, object] = {
                "part": _BROADCAST_PARTS,
                "broadcastStatus": status,
                "mine": True,
                "maxResults": 50,
            }
            if page_token is not None:
                params["pageToken"] = page_token
            response = execute_youtube_request(
                self._service.liveBroadcasts().list(**params),
                f"liveBroadcasts.list ({status}) に失敗しました",
            )
            items = _items(response, f"liveBroadcasts.list ({status})")
            broadcasts.extend(_parse_broadcast(item, f"liveBroadcasts.list ({status})") for item in items)
            payload = _object(response, f"liveBroadcasts.list ({status})")
            next_page_token = payload.get("nextPageToken")
            if next_page_token is None:
                return broadcasts
            if not isinstance(next_page_token, str) or not next_page_token:
                raise ValidationError(f"liveBroadcasts.list ({status}) nextPageToken must be a non-empty string")
            page_token = next_page_token

    def list_active_broadcasts(self) -> list[Broadcast]:
        return self._list_broadcasts("active")

    def list_upcoming_broadcasts(self) -> list[Broadcast]:
        return self._list_broadcasts("upcoming")

    def get_stream(self, stream_id: str) -> Stream:
        # Deliberately omit ``cdn``: it contains ingestionInfo.streamName (the stream key).
        response = execute_youtube_request(
            self._service.liveStreams().list(part="id,status", id=stream_id),
            "liveStreams.list に失敗しました",
        )
        items = _items(response, "liveStreams.list")
        if len(items) != 1:
            raise ValidationError(f"指定した live stream が見つかりません: {stream_id}")
        item = _object(items[0], "liveStreams.list item")
        status = _object(item.get("status"), "liveStreams.list status").get("streamStatus")
        if not isinstance(status, str) or not status:
            raise ValidationError("liveStreams.list response に streamStatus がありません")
        return Stream(id=_required_string(item, "id", "liveStreams.list item"), status=status)

    def create_broadcast(self, request: RecoveryRequest) -> Broadcast:
        response = execute_youtube_request(
            self._service.liveBroadcasts().insert(
                part="snippet,status,contentDetails",
                body={
                    "snippet": {
                        "title": request.title,
                        "scheduledStartTime": request.scheduled_start_time,
                    },
                    "status": {"privacyStatus": request.privacy_status},
                    "contentDetails": {
                        "monitorStream": {"enableMonitorStream": False},
                        "enableAutoStart": False,
                        "enableAutoStop": False,
                    },
                },
            ),
            "liveBroadcasts.insert に失敗しました",
        )
        return _parse_broadcast(response, "liveBroadcasts.insert")

    def bind_broadcast(self, broadcast_id: str, stream_id: str) -> Broadcast:
        response = execute_youtube_request(
            self._service.liveBroadcasts().bind(
                part=_BROADCAST_PARTS,
                id=broadcast_id,
                streamId=stream_id,
            ),
            "liveBroadcasts.bind に失敗しました",
        )
        return _parse_broadcast(response, "liveBroadcasts.bind")

    def transition_to_live(self, broadcast_id: str) -> Broadcast:
        response = execute_youtube_request(
            self._service.liveBroadcasts().transition(
                part=_BROADCAST_PARTS,
                id=broadcast_id,
                broadcastStatus="live",
            ),
            "liveBroadcasts.transition に失敗しました",
        )
        return _parse_broadcast(response, "liveBroadcasts.transition")


def _object(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError(f"{context} response must be an object")
    return value


def _items(response: object, context: str) -> list[object]:
    payload = _object(response, context)
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise ValidationError(f"{context} response items must be a list")
    return items


def _required_string(payload: dict[str, object], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{context} response に {key} がありません")
    return value


def _parse_broadcast(value: object, context: str) -> Broadcast:
    payload = _object(value, context)
    snippet = _object(payload.get("snippet"), f"{context} snippet")
    content_details = _object(payload.get("contentDetails", {}), f"{context} contentDetails")
    bound_stream_id = content_details.get("boundStreamId")
    if bound_stream_id is not None and not isinstance(bound_stream_id, str):
        raise ValidationError(f"{context} boundStreamId must be a string")
    return Broadcast(
        id=_required_string(payload, "id", context),
        title=_required_string(snippet, "title", f"{context} snippet"),
        bound_stream_id=bound_stream_id,
    )
