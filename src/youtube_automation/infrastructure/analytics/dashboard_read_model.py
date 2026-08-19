"""収集済み Analytics JSON の dashboard 向け読み取り専用 read model。"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias, TypedDict, cast

from youtube_automation.core.errors import DashboardChannelNotFoundError, WorkflowStateError
from youtube_automation.domains.collections.workflow_state import (
    ExecutionOwner,
    MusicEngine,
    Phase,
    Stage,
)
from youtube_automation.domains.collections.workflow_state import (
    read as read_workflow_state,
)
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


class TrendPointResponse(TypedDict):
    date: str
    views: int | float | None
    watch_time_minutes: int | float | None
    subscribers_net: int | float | None
    impressions: int | float | None


class TrendChannelResponse(TypedDict):
    id: str
    name: str
    status: str
    points: list[TrendPointResponse]
    error: ErrorResponse | None


class TrendsResponse(TypedDict):
    channels: list[TrendChannelResponse]


class PipelineEventResponse(TypedDict):
    kind: Literal["workflow_state_updated"]
    occurred_at: str


class PipelineCollectionResponse(TypedDict):
    collection_id: str
    stage: Stage | None
    phase: Phase | None
    execution_owner: ExecutionOwner | None
    handoff_status: Literal["not_started", "pending", "completed", "not_recorded", "not_applicable", "invalid"]
    latest_event: PipelineEventResponse | None
    error: ErrorResponse | None


class PipelineChannelResponse(TypedDict):
    id: str
    name: str
    collections: list[PipelineCollectionResponse]
    error: ErrorResponse | None


class PipelineResponse(TypedDict):
    channels: list[PipelineChannelResponse]


class DashboardReadModel(TypedDict):
    schema_version: int
    channels: list[ChannelDetailResponse]
    publications: PublicationsResponse
    trends: TrendsResponse
    pipeline: PipelineResponse


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


IncompleteChannelResponse: TypeAlias = dict[str, object]


class IncompleteOverviewResponse(TypedDict):
    schema_version: object
    channels: list[IncompleteChannelResponse]


DashboardOverviewResponse: TypeAlias = OverviewResponse | IncompleteOverviewResponse
DashboardChannelResponse: TypeAlias = ChannelDetailResponse | IncompleteChannelResponse


def _object(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _number(value: object, default: int | float = 0) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return default
    return value if math.isfinite(value) else default


def _non_negative_number(value: object, default: int | float = 0) -> int | float:
    number = _number(value, default)
    return number if number >= 0 else default


def _non_negative_number_or_none(value: object) -> int | float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return value if math.isfinite(value) and value >= 0 else None


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
    if status == "error":
        error = timing.get("error")
        if (
            isinstance(collections, list)
            and not collections
            and isinstance(error, dict)
            and _text(error.get("code"))
            and _text(error.get("message"))
        ):
            return timing
        return _workflow_timing_error("workflow_timing_invalid", "error workflow timing の形式が不正です")
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


def _trend_channel(channel: Path, item: ChannelDetailResponse) -> TrendChannelResponse:
    if item["status"] != "ready" or item["snapshot"] is None:
        return TrendChannelResponse(
            id=item["id"], name=item["name"], status=item["status"], points=[], error=item["error"]
        )
    try:
        snapshot = _load_snapshot(channel / "data" / item["snapshot"])
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return TrendChannelResponse(
            id=item["id"],
            name=item["name"],
            status="invalid_snapshot",
            points=[],
            error=ErrorResponse(code="snapshot_invalid", message=str(exc)),
        )
    points_by_date = _daily_trend_points(snapshot)
    _merge_daily_impressions(snapshot, points_by_date)
    return TrendChannelResponse(
        id=item["id"],
        name=item["name"],
        status="ready",
        points=[points_by_date[date] for date in sorted(points_by_date)],
        error=None,
    )


def _daily_trend_points(snapshot: dict[str, object]) -> dict[str, TrendPointResponse]:
    points_by_date: dict[str, TrendPointResponse] = {}
    daily_rows = _object(snapshot.get("channel_analytics")).get("daily_metrics")
    if isinstance(daily_rows, list):
        for row in daily_rows:
            source = _object(row)
            date = _text(source.get("date"))
            if date:
                subscribers_gained = _non_negative_number_or_none(source.get("subscribers_gained"))
                subscribers_lost = _non_negative_number_or_none(source.get("subscribers_lost"))
                points_by_date[date] = TrendPointResponse(
                    date=date,
                    views=_non_negative_number_or_none(source.get("views")),
                    watch_time_minutes=_non_negative_number_or_none(source.get("watch_time")),
                    subscribers_net=(
                        subscribers_gained - subscribers_lost
                        if subscribers_gained is not None and subscribers_lost is not None
                        else None
                    ),
                    impressions=None,
                )
    return points_by_date


def _merge_daily_impressions(snapshot: dict[str, object], points_by_date: dict[str, TrendPointResponse]) -> None:
    reporting_rows = _object(_object(snapshot.get("reporting_api")).get("impressions_summary")).get("per_day")
    if isinstance(reporting_rows, list):
        for row in reporting_rows:
            source = _object(row)
            date = _text(source.get("date"))
            if not date:
                continue
            point = points_by_date.get(
                date,
                TrendPointResponse(
                    date=date,
                    views=None,
                    watch_time_minutes=None,
                    subscribers_net=None,
                    impressions=None,
                ),
            )
            points_by_date[date] = TrendPointResponse(
                date=point["date"],
                views=point["views"],
                watch_time_minutes=point["watch_time_minutes"],
                subscribers_net=point["subscribers_net"],
                impressions=_non_negative_number_or_none(source.get("impressions")),
            )


def _pipeline_owner(phase: Phase, engine: MusicEngine | None) -> ExecutionOwner:
    if phase == "prepared" and engine == "suno":
        return "local"
    return "cloud"


def _handoff_status(
    phase: Phase,
    engine: MusicEngine | None,
    *,
    handoff_complete: bool,
) -> Literal["not_started", "pending", "completed", "not_recorded", "not_applicable"]:
    if engine != "suno":
        return "not_applicable"
    if handoff_complete:
        return "completed"
    if phase == "planning":
        return "not_started"
    return "pending" if phase == "prepared" else "not_recorded"


def _invalid_pipeline_collection(collection_id: str, message: str) -> PipelineCollectionResponse:
    return PipelineCollectionResponse(
        collection_id=collection_id,
        stage=None,
        phase=None,
        execution_owner=None,
        handoff_status="invalid",
        latest_event=None,
        error=ErrorResponse(code="workflow_state_invalid", message=message),
    )


def _pipeline_collection(collection: Path, state_path: Path) -> PipelineCollectionResponse:
    try:
        if collection.is_symlink() or state_path.is_symlink():
            raise WorkflowStateError(f"workflow-state path に symlink は使えません: {state_path}")
        state = read_workflow_state(state_path)
        phase = state.phase
        stage = state.stage
        if phase is None:
            raise WorkflowStateError("workflow-state.json::phase がありません")
        if stage is None:
            raise WorkflowStateError("workflow-state.json::stage がありません")
        engine = state.music_engine
        handoff = state.handoff
        complete = (
            handoff is not None
            and handoff.point == "suno_download"
            and handoff.owner == "cloud"
            and handoff.manifest_key is not None
            and handoff.root_sha256 is not None
        )
        updated_at = state.updated_at
    except (OSError, WorkflowStateError) as exc:
        return _invalid_pipeline_collection(collection.name, str(exc))
    return PipelineCollectionResponse(
        collection_id=collection.name,
        stage=stage,
        phase=phase,
        execution_owner=(
            handoff.owner if handoff is not None and handoff.owner is not None else _pipeline_owner(phase, engine)
        ),
        handoff_status=_handoff_status(phase, engine, handoff_complete=complete),
        latest_event=(
            PipelineEventResponse(kind="workflow_state_updated", occurred_at=updated_at)
            if updated_at is not None
            else None
        ),
        error=None,
    )


def _pipeline_channels(
    channel_paths: list[Path],
    channels: list[ChannelDetailResponse],
) -> PipelineResponse:
    result: list[PipelineChannelResponse] = []
    for channel, item in zip(channel_paths, channels, strict=True):
        collections: list[PipelineCollectionResponse] = []
        error: ErrorResponse | None = None
        collections_root = channel / "collections"
        try:
            if collections_root.is_symlink():
                raise WorkflowStateError(f"collections directory に symlink は使えません: {collections_root}")
            for stage in ("planning", "live"):
                area = collections_root / stage
                if not area.exists():
                    continue
                if area.is_symlink() or not area.is_dir():
                    raise WorkflowStateError(f"collection area が不正です: {area}")
                for collection in sorted(area.iterdir(), key=lambda path: path.name):
                    state_path = collection / "workflow-state.json"
                    if not state_path.exists():
                        continue
                    collections.append(_pipeline_collection(collection, state_path))
        except (OSError, WorkflowStateError) as exc:
            collections = []
            error = ErrorResponse(code="workflow_state_discovery_failed", message=str(exc))
        result.append(PipelineChannelResponse(id=item["id"], name=item["name"], collections=collections, error=error))
    return PipelineResponse(channels=result)


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
        trends=TrendsResponse(
            channels=[_trend_channel(path, item) for path, item in zip(channel_paths, channels, strict=True)]
        ),
        pipeline=_pipeline_channels(channel_paths, channels),
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

    @staticmethod
    def _overview_channel(item: ChannelDetailResponse) -> ChannelOverviewResponse:
        videos = item["videos"]
        return ChannelOverviewResponse(
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

    @staticmethod
    def _incomplete_overview_channel(item: Mapping[str, object]) -> dict[str, object]:
        videos = item.get("videos")
        overview = {key: value for key, value in item.items() if key not in {"videos", "workflow_timing"}}
        overview["video_count"] = len(videos) if isinstance(videos, list) else 0
        return overview

    def overview(self) -> DashboardOverviewResponse:
        """動画行を除いた全チャンネル概要を返す。"""
        channels = self._channels()
        if any(not ChannelDetailResponse.__required_keys__ <= item.keys() for item in channels):
            return IncompleteOverviewResponse(
                schema_version=self.model.get("schema_version", SCHEMA_VERSION),
                channels=[self._incomplete_overview_channel(item) for item in channels],
            )
        return OverviewResponse(
            schema_version=self.model.get("schema_version", SCHEMA_VERSION),
            channels=[self._overview_channel(item) for item in channels],
        )

    def channel(self, channel_id: str) -> DashboardChannelResponse:
        """選択チャンネルの動画を含む詳細を返す。"""
        for item in self._channels():
            if item.get("id") == channel_id:
                if ChannelDetailResponse.__required_keys__ <= item.keys():
                    detail: DashboardChannelResponse = item.copy()
                else:
                    detail = dict(item.items())
                if not isinstance(detail.get("videos"), list):
                    detail["videos"] = []
                return detail
        raise DashboardChannelNotFoundError(f"dashboard channel が見つかりません: {channel_id}")

    def trends(self) -> TrendsResponse:
        """登録順のチャンネル別日次再生数を返す。"""
        trends = self.model.get("trends")
        return trends if isinstance(trends, dict) else TrendsResponse(channels=[])

    def pipeline(self) -> PipelineResponse:
        """Git管理 workflow state から作った工程所有権の一覧を返す。"""
        pipeline = self.model.get("pipeline")
        return pipeline if isinstance(pipeline, dict) else PipelineResponse(channels=[])
