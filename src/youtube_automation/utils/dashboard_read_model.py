"""収集済み Analytics JSON の dashboard 向け読み取り専用 read model。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from youtube_automation.utils.exceptions import DashboardChannelNotFoundError

SCHEMA_VERSION = 1


def _object(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _number(value: object, default: int | float = 0) -> int | float:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _channel_id(channel: Path) -> str:
    digest = hashlib.sha256(str(channel).encode("utf-8")).hexdigest()[:16]
    return f"channel-{digest}"


def _reporting_by_video(snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
    summary = _object(_object(snapshot.get("reporting_api")).get("impressions_summary"))
    rows = summary.get("per_video")
    if not isinstance(rows, list):
        return {}
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        item = _object(row)
        video_id = _text(item.get("video_id"))
        if video_id:
            result[video_id] = item
    return result


def _videos(snapshot: dict[str, object]) -> list[dict[str, object]]:
    analytics = _object(snapshot.get("video_analytics"))
    reporting = _reporting_by_video(snapshot)
    videos: list[dict[str, object]] = []
    for key, raw in analytics.items():
        source = _object(raw)
        video_id = _text(source.get("video_id"), key)
        reach = reporting.get(video_id, {})
        likes = _number(source.get("likes"))
        comments = _number(source.get("comments"))
        shares = _number(source.get("shares"))
        videos.append(
            {
                "video_id": video_id,
                "title": _text(source.get("title"), "Unknown"),
                "views": _number(source.get("views")),
                "impressions": _number(reach.get("impressions")),
                "ctr_percentage": _number(reach.get("ctr_percentage")),
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "subscribers_gained": _number(source.get("subscribers_gained")),
                "average_view_duration_seconds": _number(source.get("average_view_duration")),
                "engagements": likes + comments + shares,
            }
        )
    return sorted(videos, key=lambda item: (-cast(int | float, item["views"]), cast(str, item["video_id"])))


def _error_channel(
    channel: Path,
    *,
    name: str,
    status: str,
    code: str,
    message: str,
) -> dict[str, object]:
    return {
        "id": _channel_id(channel),
        "name": name,
        "status": status,
        "snapshot": None,
        "collected_at": None,
        "period": {"start_date": None, "end_date": None},
        "summary": None,
        "videos": [],
        "error": {"code": code, "message": message},
    }


def _load_name(channel: Path) -> str:
    meta_path = channel / "config" / "channel" / "meta.json"
    meta_value = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta_value, dict):
        raise ValueError("meta.json root は object でなければなりません")
    name = _text(_object(meta_value.get("channel")).get("name"))
    if not name:
        raise ValueError("meta.json の channel.name がありません")
    return name


def _load_snapshot(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Analytics snapshot root は object でなければなりません")
    return cast(dict[str, object], value)


def _ready_channel(
    channel: Path,
    *,
    name: str,
    snapshot_path: Path,
    snapshot: dict[str, object],
) -> dict[str, object]:
    period = _object(snapshot.get("collection_period"))
    summary = _object(_object(snapshot.get("channel_analytics")).get("summary"))
    return {
        "id": _channel_id(channel),
        "name": name,
        "status": "ready",
        "snapshot": snapshot_path.name,
        "collected_at": _text(period.get("collected_at")) or None,
        "period": {
            "start_date": _text(period.get("start_date")) or None,
            "end_date": _text(period.get("end_date")) or None,
        },
        "summary": {
            "views": _number(summary.get("total_views")),
            "watch_time_minutes": _number(summary.get("total_watch_time")),
            "subscribers_net": _number(summary.get("net_subscribers")),
            "engagements": _number(summary.get("total_engagement")),
            "average_view_percentage": _number(summary.get("avg_view_percentage")),
        },
        "videos": _videos(snapshot),
        "error": None,
    }


def _build_channel(channel: Path) -> dict[str, object]:
    try:
        name = _load_name(channel)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return _error_channel(
            channel,
            name=channel.name,
            status="invalid_channel",
            code="meta_invalid",
            message=str(exc),
        )

    snapshots = sorted((channel / "data").glob("analytics_data_*.json"))
    if not snapshots:
        return _error_channel(
            channel,
            name=name,
            status="missing_snapshot",
            code="snapshot_missing",
            message=f"Analytics snapshot がありません: {channel / 'data'}",
        )
    snapshot_path = snapshots[-1]
    try:
        snapshot = _load_snapshot(snapshot_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return _error_channel(
            channel,
            name=name,
            status="invalid_snapshot",
            code="snapshot_invalid",
            message=str(exc),
        )
    return _ready_channel(channel, name=name, snapshot_path=snapshot_path, snapshot=snapshot)


def build_dashboard_read_model(channel_paths: list[Path]) -> dict[str, object]:
    """登録順のチャンネルから JSON serializable な read model を作る。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "channels": [_build_channel(channel) for channel in channel_paths],
    }


@dataclass(frozen=True)
class DashboardAPI:
    """HTTP layer が利用する読み取り専用 JSON API service。"""

    model: dict[str, object]

    def _channels(self) -> list[dict[str, object]]:
        channels = self.model.get("channels")
        if not isinstance(channels, list):
            return []
        return [cast(dict[str, object], item) for item in channels if isinstance(item, dict)]

    def overview(self) -> dict[str, object]:
        """動画行を除いた全チャンネル概要を返す。"""
        overview_channels: list[dict[str, object]] = []
        for item in self._channels():
            videos = item.get("videos")
            overview = {key: value for key, value in item.items() if key != "videos"}
            overview["video_count"] = len(videos) if isinstance(videos, list) else 0
            overview_channels.append(overview)
        return {
            "schema_version": self.model.get("schema_version", SCHEMA_VERSION),
            "channels": overview_channels,
        }

    def channel(self, channel_id: str) -> dict[str, object]:
        """選択チャンネルの動画を含む詳細を返す。"""
        for item in self._channels():
            if item.get("id") == channel_id:
                return item
        raise DashboardChannelNotFoundError(f"dashboard channel が見つかりません: {channel_id}")
