"""収集済み Analytics JSON の dashboard 向け読み取り専用 read model。"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

from youtube_automation.core.errors import DashboardChannelNotFoundError
from youtube_automation.infrastructure.analytics.dashboard_publications import (
    DashboardPublicationError,
    load_dashboard_publications,
)

SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1


class ErrorResponse(TypedDict):
    code: str
    message: str


class PeriodResponse(TypedDict):
    start_date: str | None
    end_date: str | None


class SummaryResponse(TypedDict):
    views: int | float
    watch_time_minutes: int | float
    subscribers_net: int | float
    engagements: int | float
    average_view_percentage: int | float


class VideoResponse(TypedDict):
    video_id: str
    title: str
    views: int | float
    impressions: int | float
    ctr_percentage: int | float
    likes: int | float
    comments: int | float
    shares: int | float
    subscribers_gained: int | float
    average_view_duration_seconds: int | float
    engagements: int | float


class ChannelSourceResponse(TypedDict):
    id: str
    name: str
    status: str
    snapshot: str | None
    collected_at: str | None
    period: PeriodResponse
    scheduled_count: int | None
    summary: SummaryResponse | None
    videos: list[VideoResponse]
    error: ErrorResponse | None


class ChannelWorkflowTimingResponse(TypedDict, total=False):
    workflow_timing: dict[str, object]


class ChannelDetailResponse(ChannelSourceResponse, ChannelWorkflowTimingResponse):
    refresh_error: ErrorResponse | None


class PublicationChannelResponse(TypedDict):
    id: str
    name: str
    status: str
    fetched_at: str | None
    timezone: str | None
    days: dict[str, int]
    error: DashboardPublicationError | None


class PublicationsResponse(TypedDict):
    days: dict[str, int]
    channels: list[PublicationChannelResponse]


class DashboardReadModel(TypedDict):
    schema_version: int
    channels: list[ChannelDetailResponse]
    publications: PublicationsResponse


class ChannelOverviewResponse(TypedDict):
    id: str
    name: str
    status: str
    snapshot: str | None
    collected_at: str | None
    period: PeriodResponse
    scheduled_count: int | None
    summary: SummaryResponse | None
    error: ErrorResponse | None
    refresh_error: ErrorResponse | None
    video_count: int


class OverviewResponse(TypedDict):
    schema_version: int
    channels: list[ChannelOverviewResponse]


def _object(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _number(value: object, default: int | float = 0) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return default
    return value if math.isfinite(value) else default


def _non_negative_number(value: object, default: int | float = 0) -> int | float:
    number = _number(value, default)
    return number if number >= 0 else default


def _text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _integer_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _workflow_timing_error(code: str, message: str) -> dict[str, object]:
    return {
        "status": "error",
        "collections": [],
        "error": {"code": code, "message": message},
    }


def _workflow_timing(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return _workflow_timing_error("workflow_timing_invalid", "workflow timing は object ではありません")
    timing = cast(dict[str, object], value)
    status = timing.get("status")
    collections = timing.get("collections")
    if status not in {"ready", "unavailable", "in_progress"} or not isinstance(collections, list):
        return _workflow_timing_error("workflow_timing_invalid", "workflow timing の status/collections が不正です")
    if any(not isinstance(collection, dict) for collection in collections):
        return _workflow_timing_error("workflow_timing_invalid", "workflow timing collection は object ではありません")
    if status == "unavailable" and not _text(timing.get("reason")):
        return _workflow_timing_error("workflow_timing_invalid", "unavailable workflow timing に reason がありません")
    return timing


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


def _videos(snapshot: dict[str, object]) -> list[VideoResponse]:
    analytics = _object(snapshot.get("video_analytics"))
    reporting = _reporting_by_video(snapshot)
    videos: list[VideoResponse] = []
    for key, raw in analytics.items():
        source = _object(raw)
        video_id = _text(source.get("video_id"), key)
        reach = reporting.get(video_id, {})
        likes = _non_negative_number(source.get("likes"))
        comments = _non_negative_number(source.get("comments"))
        shares = _non_negative_number(source.get("shares"))
        videos.append(
            VideoResponse(
                video_id=video_id,
                title=_text(source.get("title"), "Unknown"),
                views=_non_negative_number(source.get("views")),
                impressions=_non_negative_number(reach.get("impressions")),
                ctr_percentage=_non_negative_number(reach.get("ctr_percentage")),
                likes=likes,
                comments=comments,
                shares=shares,
                subscribers_gained=_non_negative_number(source.get("subscribers_gained")),
                average_view_duration_seconds=_non_negative_number(source.get("average_view_duration")),
                engagements=likes + comments + shares,
            )
        )
    return sorted(videos, key=lambda item: (-cast(int | float, item["views"]), cast(str, item["video_id"])))


def _error_channel(
    channel: Path,
    *,
    name: str,
    status: str,
    code: str,
    message: str,
) -> ChannelSourceResponse:
    return ChannelSourceResponse(
        id=_channel_id(channel),
        name=name,
        status=status,
        snapshot=None,
        collected_at=None,
        period=PeriodResponse(start_date=None, end_date=None),
        scheduled_count=None,
        summary=None,
        videos=[],
        error=ErrorResponse(code=code, message=message),
    )


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
) -> ChannelSourceResponse:
    period = _object(snapshot.get("collection_period"))
    summary = _object(_object(snapshot.get("channel_analytics")).get("summary"))
    scheduled = _object(snapshot.get("scheduled_videos"))
    return ChannelSourceResponse(
        id=_channel_id(channel),
        name=name,
        status="ready",
        snapshot=snapshot_path.name,
        collected_at=_text(period.get("collected_at")) or None,
        period=PeriodResponse(
            start_date=_text(period.get("start_date")) or None,
            end_date=_text(period.get("end_date")) or None,
        ),
        scheduled_count=_integer_or_none(scheduled.get("count")),
        summary=SummaryResponse(
            views=_non_negative_number(summary.get("total_views")),
            watch_time_minutes=_non_negative_number(summary.get("total_watch_time")),
            subscribers_net=_number(summary.get("net_subscribers")),
            engagements=_non_negative_number(summary.get("total_engagement")),
            average_view_percentage=_non_negative_number(summary.get("avg_view_percentage")),
        ),
        videos=_videos(snapshot),
        error=None,
    )


def _build_channel(channel: Path, *, allow_snapshot_fallback: bool = False) -> ChannelSourceResponse:
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
    latest_error = "Analytics snapshot を読み込めません"
    candidates = list(reversed(snapshots)) if allow_snapshot_fallback else [snapshots[-1]]
    for snapshot_path in candidates:
        try:
            snapshot = _load_snapshot(snapshot_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            if snapshot_path == snapshots[-1]:
                latest_error = str(exc)
            continue
        return _ready_channel(channel, name=name, snapshot_path=snapshot_path, snapshot=snapshot)
    return _error_channel(
        channel,
        name=name,
        status="invalid_snapshot",
        code="snapshot_invalid",
        message=latest_error,
    )


def _publication_channel(channel: Path, item: ChannelDetailResponse) -> PublicationChannelResponse:
    publication_path = channel / "data" / "dashboard_publications.json"
    payload = load_dashboard_publications(publication_path)
    if payload is None:
        return PublicationChannelResponse(
            id=item["id"],
            name=item["name"],
            status="invalid" if publication_path.exists() else "missing",
            fetched_at=None,
            timezone=None,
            days={},
            error=None,
        )

    error = payload.get("error")
    return PublicationChannelResponse(
        id=item["id"],
        name=item["name"],
        status="refresh_failed" if error is not None else "ready",
        fetched_at=payload["fetched_at"],
        timezone=payload["timezone"],
        days=payload["days"],
        error=error,
    )


def _publication_read_model(
    channel_paths: list[Path],
    channels: list[ChannelDetailResponse],
) -> PublicationsResponse:
    totals: dict[str, int] = {}
    publication_channels: list[PublicationChannelResponse] = []
    for channel, item in zip(channel_paths, channels, strict=True):
        publication = _publication_channel(channel, item)
        publication_channels.append(publication)
        days = publication["days"]
        for local_day, count in days.items():
            totals[local_day] = totals.get(local_day, 0) + count
    return PublicationsResponse(days=dict(sorted(totals.items())), channels=publication_channels)


def build_dashboard_read_model(
    channel_paths: list[Path],
    *,
    refresh_errors: dict[Path, str] | None = None,
    workflow_timing_by_channel: Mapping[Path, object] | None = None,
) -> DashboardReadModel:
    """登録順のチャンネルから JSON serializable な read model を作る。"""
    errors = refresh_errors or {}
    workflow_timings = workflow_timing_by_channel or {}
    timing_requested = workflow_timing_by_channel is not None
    channels: list[ChannelDetailResponse] = []
    for channel in channel_paths:
        refresh_message = errors.get(channel)
        source = _build_channel(channel, allow_snapshot_fallback=refresh_message is not None)
        item = ChannelDetailResponse(
            **source,
            refresh_error=(
                ErrorResponse(code="refresh_failed", message=refresh_message) if refresh_message is not None else None
            ),
        )
        if timing_requested:
            if channel in workflow_timings:
                item["workflow_timing"] = _workflow_timing(workflow_timings[channel])
            else:
                item["workflow_timing"] = _workflow_timing_error(
                    "workflow_timing_missing",
                    "channel の workflow timing がありません",
                )
        channels.append(item)
    return DashboardReadModel(
        schema_version=SCHEMA_VERSION if timing_requested else LEGACY_SCHEMA_VERSION,
        channels=channels,
        publications=_publication_read_model(channel_paths, channels),
    )


@dataclass(frozen=True)
class DashboardAPI:
    """HTTP layer が利用する読み取り専用 JSON API service。"""

    model: DashboardReadModel

    def _channels(self) -> list[ChannelDetailResponse]:
        channels = self.model.get("channels")
        if not isinstance(channels, list):
            return []
        return [item for item in channels if isinstance(item, dict)]

    def overview(self) -> OverviewResponse:
        """動画行を除いた全チャンネル概要を返す。"""
        overview_channels: list[ChannelOverviewResponse] = []
        for item in self._channels():
            videos = item.get("videos")
            if not ChannelSourceResponse.__required_keys__ <= item.keys():
                # DashboardAPI の型付き入力契約より前から、直接生成した不完全な
                # model を best-effort で返す互換挙動がある。完全な型を一度作り、
                # 実際の入力に存在しなかった required key だけを動的に除くことで、
                # 正規 builder 経路の required-key 契約は弱めずに維持する。
                legacy_overview = ChannelOverviewResponse(
                    id=item.get("id", ""),
                    name=item.get("name", ""),
                    status=item.get("status", ""),
                    snapshot=item.get("snapshot"),
                    collected_at=item.get("collected_at"),
                    period=item.get("period", PeriodResponse(start_date=None, end_date=None)),
                    scheduled_count=item.get("scheduled_count"),
                    summary=item.get("summary"),
                    error=item.get("error"),
                    refresh_error=item.get("refresh_error"),
                    video_count=len(videos) if isinstance(videos, list) else 0,
                )
                for key in ChannelOverviewResponse.__required_keys__ - item.keys() - {"video_count"}:
                    legacy_overview.pop(key, None)
                overview_channels.append(legacy_overview)
                continue
            overview = ChannelOverviewResponse(
                id=item["id"],
                name=item["name"],
                status=item["status"],
                snapshot=item["snapshot"],
                collected_at=item["collected_at"],
                period=item["period"],
                scheduled_count=item["scheduled_count"],
                summary=item["summary"],
                error=item["error"],
                refresh_error=item["refresh_error"],
                video_count=len(videos) if isinstance(videos, list) else 0,
            )
            overview_channels.append(overview)
        return OverviewResponse(
            schema_version=self.model.get("schema_version", SCHEMA_VERSION),
            channels=overview_channels,
        )

    def channel(self, channel_id: str) -> ChannelDetailResponse:
        """選択チャンネルの動画を含む詳細を返す。"""
        for item in self._channels():
            if item.get("id") == channel_id:
                detail = item.copy()
                if not isinstance(detail.get("videos"), list):
                    detail["videos"] = []
                return detail
        raise DashboardChannelNotFoundError(f"dashboard channel が見つかりません: {channel_id}")
