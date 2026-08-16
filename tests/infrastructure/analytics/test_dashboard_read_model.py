"""Dashboard read model/API の public contract。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import is_typeddict

import pytest

from youtube_automation.core.errors import DashboardChannelNotFoundError
from youtube_automation.infrastructure.analytics.dashboard_read_model import (
    ChannelDetailResponse,
    ChannelOverviewResponse,
    DashboardAPI,
    DashboardReadModel,
    OverviewResponse,
    PublicationChannelResponse,
    PublicationsResponse,
    build_dashboard_read_model,
)


def _write_channel(channel: Path, *, name: str, snapshots: dict[str, dict]) -> None:
    meta = channel / "config" / "channel" / "meta.json"
    meta.parent.mkdir(parents=True)
    meta.write_text(json.dumps({"channel": {"name": name}}), encoding="utf-8")
    data = channel / "data"
    data.mkdir()
    for filename, payload in snapshots.items():
        (data / filename).write_text(json.dumps(payload), encoding="utf-8")


def _snapshot(*, collected_at: str, views: int, video_views: int) -> dict:
    return {
        "collection_period": {
            "start_date": "2026-07-01",
            "end_date": "2026-07-20",
            "collected_at": collected_at,
        },
        "channel_analytics": {
            "daily_metrics": [
                {"date": "2026-07-19", "views": 12, "watch_time": 30},
                {"date": "2026-07-20", "views": 18},
            ],
            "summary": {
                "total_views": views,
                "total_watch_time": 420,
                "net_subscribers": 8,
                "total_engagement": 31,
                "avg_view_percentage": 62.5,
            },
        },
        "scheduled_videos": {"count": 2},
        "video_analytics": {
            "video-b": {
                "video_id": "video-b",
                "title": "Later video",
                "views": video_views,
                "likes": 20,
                "comments": 4,
                "shares": 3,
                "subscribers_gained": 2,
                "average_view_duration": 180,
            }
        },
        "reporting_api": {
            "impressions_summary": {"per_video": [{"video_id": "video-b", "impressions": 1000, "ctr_percentage": 4.5}]}
        },
    }


def _write_publications(
    channel: Path,
    *,
    fetched_at: str,
    timezone: str,
    days: dict[str, int],
    error: dict[str, str] | None = None,
) -> None:
    payload: dict[str, object] = {
        "schema_version": 1,
        "fetched_at": fetched_at,
        "timezone": timezone,
        "days": days,
    }
    if error is not None:
        payload["error"] = error
    (channel / "data" / "dashboard_publications.json").write_text(json.dumps(payload), encoding="utf-8")


def test_dashboard_api_response_contracts_are_typed_dicts() -> None:
    assert is_typeddict(DashboardReadModel)
    assert is_typeddict(OverviewResponse)


def test_trends_extract_daily_views_without_changing_channel_response(tmp_path: Path) -> None:
    channel = tmp_path / "ready"
    _write_channel(
        channel,
        name="Night Drive",
        snapshots={"analytics_data_2026-07-20.json": _snapshot(collected_at="now", views=30, video_views=20)},
    )
    api = DashboardAPI(build_dashboard_read_model([channel]))

    trend = api.trends()["channels"][0]
    assert trend["name"] == "Night Drive"
    assert trend["points"] == [
        {"date": "2026-07-19", "views": 12},
        {"date": "2026-07-20", "views": 18},
    ]
    assert "points" not in api.overview()["channels"][0]
    assert is_typeddict(ChannelOverviewResponse)
    assert is_typeddict(ChannelDetailResponse)
    assert is_typeddict(PublicationsResponse)
    assert is_typeddict(PublicationChannelResponse)
    assert DashboardReadModel.__required_keys__ == frozenset(
        {"schema_version", "channels", "publications", "trends", "pipeline"}
    )
    assert OverviewResponse.__required_keys__ == frozenset({"schema_version", "channels"})
    assert ChannelOverviewResponse.__required_keys__ == frozenset(
        {
            "id",
            "name",
            "status",
            "snapshot",
            "collected_at",
            "period",
            "scheduled_count",
            "summary",
            "error",
            "refresh_error",
            "video_count",
        }
    )
    assert ChannelDetailResponse.__required_keys__ == frozenset(
        {
            "id",
            "name",
            "status",
            "snapshot",
            "collected_at",
            "period",
            "scheduled_count",
            "summary",
            "videos",
            "error",
            "refresh_error",
        }
    )
    assert ChannelDetailResponse.__optional_keys__ == frozenset({"workflow_timing"})
    assert PublicationsResponse.__required_keys__ == frozenset({"days", "channels"})
    assert PublicationChannelResponse.__required_keys__ == frozenset(
        {"id", "name", "status", "fetched_at", "timezone", "days", "error"}
    )


def test_read_model_aggregates_publication_days_and_channel_cache_state(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for channel, name in ((first, "First"), (second, "Second")):
        _write_channel(
            channel,
            name=name,
            snapshots={
                "analytics_data_20260720.json": _snapshot(
                    collected_at="2026-07-20T00:00:00+00:00", views=900, video_views=700
                )
            },
        )
    _write_publications(
        first,
        fetched_at="2026-08-08T12:00:00+00:00",
        timezone="Asia/Tokyo",
        days={"2026-08-07": 2, "2026-08-08": 3},
    )
    publication_error = {
        "code": "publication_refresh_failed",
        "message": "quota exceeded",
        "attempted_at": "2026-08-08T13:00:00+00:00",
    }
    _write_publications(
        second,
        fetched_at="2026-08-07T12:00:00+00:00",
        timezone="UTC",
        days={"2026-08-08": 4},
        error=publication_error,
    )

    model = build_dashboard_read_model([first, second])

    assert model["publications"] == {
        "days": {"2026-08-07": 2, "2026-08-08": 7},
        "channels": [
            {
                "id": model["channels"][0]["id"],
                "name": "First",
                "status": "ready",
                "fetched_at": "2026-08-08T12:00:00+00:00",
                "timezone": "Asia/Tokyo",
                "days": {"2026-08-07": 2, "2026-08-08": 3},
                "error": None,
            },
            {
                "id": model["channels"][1]["id"],
                "name": "Second",
                "status": "refresh_failed",
                "fetched_at": "2026-08-07T12:00:00+00:00",
                "timezone": "UTC",
                "days": {"2026-08-08": 4},
                "error": publication_error,
            },
        ],
    }


def test_read_model_isolates_missing_and_invalid_publication_caches(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    invalid = tmp_path / "invalid"
    ready = tmp_path / "ready"
    for channel, name in ((missing, "Missing"), (invalid, "Invalid"), (ready, "Ready")):
        _write_channel(channel, name=name, snapshots={})
    (invalid / "data" / "dashboard_publications.json").write_text("not-json", encoding="utf-8")
    _write_publications(
        ready,
        fetched_at="2026-08-08T12:00:00+00:00",
        timezone="UTC",
        days={"2026-08-08": 5},
    )

    publications = build_dashboard_read_model([missing, invalid, ready])["publications"]

    assert publications["days"] == {"2026-08-08": 5}
    assert [channel["status"] for channel in publications["channels"]] == ["missing", "invalid", "ready"]
    assert publications["channels"][0]["fetched_at"] is None
    assert publications["channels"][1]["days"] == {}


def test_read_model_uses_latest_snapshot_and_normalizes_metrics(tmp_path: Path) -> None:
    channel = tmp_path / "channel-one"
    _write_channel(
        channel,
        name="Channel One",
        snapshots={
            "analytics_data_20260701.json": _snapshot(
                collected_at="2026-07-01T00:00:00+00:00", views=100, video_views=40
            ),
            "analytics_data_20260720.json": _snapshot(
                collected_at="2026-07-20T00:00:00+00:00", views=900, video_views=700
            ),
        },
    )

    model = build_dashboard_read_model([channel])

    assert model["schema_version"] == 1
    item = model["channels"][0]
    assert item["name"] == "Channel One"
    assert item["status"] == "ready"
    assert item["snapshot"] == "analytics_data_20260720.json"
    assert item["collected_at"] == "2026-07-20T00:00:00+00:00"
    assert item["scheduled_count"] == 2
    assert item["summary"] == {
        "views": 900,
        "watch_time_minutes": 420,
        "subscribers_net": 8,
        "engagements": 31,
        "average_view_percentage": 62.5,
    }
    assert item["videos"] == [
        {
            "video_id": "video-b",
            "title": "Later video",
            "views": 700,
            "impressions": 1000,
            "ctr_percentage": 4.5,
            "likes": 20,
            "comments": 4,
            "shares": 3,
            "subscribers_gained": 2,
            "average_view_duration_seconds": 180,
            "engagements": 27,
        }
    ]


def test_read_model_keeps_other_channels_when_snapshot_is_missing_or_broken(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    _write_channel(
        ready,
        name="Ready",
        snapshots={
            "analytics_data_20260720.json": _snapshot(
                collected_at="2026-07-20T00:00:00+00:00", views=900, video_views=700
            )
        },
    )
    missing = tmp_path / "missing"
    _write_channel(missing, name="Missing", snapshots={})
    broken = tmp_path / "broken"
    _write_channel(broken, name="Broken", snapshots={})
    (broken / "data" / "analytics_data_20260720.json").write_text("not-json", encoding="utf-8")

    model = build_dashboard_read_model([missing, ready, broken])

    channels = model["channels"]
    assert [item["name"] for item in channels] == ["Missing", "Ready", "Broken"]
    assert channels[0]["status"] == "missing_snapshot"
    assert channels[0]["error"]["code"] == "snapshot_missing"
    assert channels[0]["videos"] == []
    assert channels[1]["status"] == "ready"
    assert channels[2]["status"] == "invalid_snapshot"
    assert channels[2]["error"]["code"] == "snapshot_invalid"


def test_read_model_marks_invalid_meta_without_stopping_other_channels(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid-meta"
    (invalid / "config" / "channel").mkdir(parents=True)
    (invalid / "config" / "channel" / "meta.json").write_text("{}", encoding="utf-8")

    item = build_dashboard_read_model([invalid])["channels"][0]

    assert item["status"] == "invalid_channel"
    assert item["error"]["code"] == "meta_invalid"
    assert item["name"] == "invalid-meta"


def test_dashboard_api_exposes_overview_and_selected_channel(tmp_path: Path) -> None:
    channel = tmp_path / "channel"
    _write_channel(
        channel,
        name="Selected",
        snapshots={
            "analytics_data_20260720.json": _snapshot(
                collected_at="2026-07-20T00:00:00+00:00", views=900, video_views=700
            )
        },
    )
    api = DashboardAPI(build_dashboard_read_model([channel]))

    overview = api.overview()
    channel_id = overview["channels"][0]["id"]

    assert "videos" not in overview["channels"][0]
    assert overview["channels"][0]["video_count"] == 1
    assert "workflow_timing" not in api.channel(channel_id)
    assert api.channel(channel_id)["videos"][0]["video_id"] == "video-b"
    with pytest.raises(DashboardChannelNotFoundError, match="unknown"):
        api.channel("unknown")


def test_dashboard_api_exposes_workflow_timing_only_in_channel_detail(tmp_path: Path) -> None:
    channel = tmp_path / "channel"
    _write_channel(
        channel,
        name="Selected",
        snapshots={
            "analytics_data_20260720.json": _snapshot(
                collected_at="2026-07-20T00:00:00+00:00", views=900, video_views=700
            )
        },
    )
    timing = {
        "status": "ready",
        "collections": [
            {
                "collection_id": "active",
                "stage": "planning",
                "steps": [],
                "totals": {"work_seconds": 0},
            }
        ],
    }

    api = DashboardAPI(build_dashboard_read_model([channel], workflow_timing_by_channel={channel: timing}))
    overview = api.overview()
    channel_id = overview["channels"][0]["id"]

    assert "workflow_timing" not in overview["channels"][0]
    assert api.channel(channel_id)["workflow_timing"] == timing


@pytest.mark.parametrize(
    ("broken_timing", "error_code"),
    [
        (None, "workflow_timing_missing"),
        ({"status": "ready", "collections": "not-an-array"}, "workflow_timing_invalid"),
    ],
)
def test_read_model_isolates_missing_or_malformed_workflow_timing_by_channel(
    tmp_path: Path,
    broken_timing: object,
    error_code: str,
) -> None:
    healthy = tmp_path / "healthy"
    broken = tmp_path / "broken"
    for channel, name, views in ((healthy, "Healthy", 900), (broken, "Broken timing", 700)):
        _write_channel(
            channel,
            name=name,
            snapshots={
                "analytics_data_20260720.json": _snapshot(
                    collected_at="2026-07-20T00:00:00+00:00",
                    views=views,
                    video_views=views - 100,
                )
            },
        )
    healthy_timing = {"status": "ready", "collections": []}
    timings: dict[Path, object] = {healthy: healthy_timing}
    if broken_timing is not None:
        timings[broken] = broken_timing

    channels = build_dashboard_read_model(
        [broken, healthy],
        workflow_timing_by_channel=timings,
    )["channels"]

    broken_item, healthy_item = channels
    assert broken_item["status"] == "ready"
    assert broken_item["summary"]["views"] == 700
    assert broken_item["videos"][0]["video_id"] == "video-b"
    assert broken_item["workflow_timing"]["status"] == "error"
    assert broken_item["workflow_timing"]["error"]["code"] == error_code
    assert healthy_item["summary"]["views"] == 900
    assert healthy_item["workflow_timing"] == healthy_timing


def test_read_model_keeps_previous_snapshot_with_structured_refresh_error(tmp_path: Path) -> None:
    channel = tmp_path / "stale"
    _write_channel(
        channel,
        name="Stale but visible",
        snapshots={
            "analytics_data_20260720.json": _snapshot(
                collected_at="2026-07-20T00:00:00+00:00", views=900, video_views=700
            )
        },
    )

    item = build_dashboard_read_model([channel], refresh_errors={channel: "authentication failed"})["channels"][0]

    assert item["summary"]["views"] == 900
    assert item["refresh_error"] == {
        "code": "refresh_failed",
        "message": "authentication failed",
    }


def test_read_model_falls_back_to_previous_valid_snapshot_after_partial_write(tmp_path: Path) -> None:
    channel = tmp_path / "partial-write"
    _write_channel(
        channel,
        name="Previous snapshot",
        snapshots={
            "analytics_data_20260720.json": _snapshot(
                collected_at="2026-07-20T00:00:00+00:00", views=900, video_views=700
            )
        },
    )
    (channel / "data" / "analytics_data_20260721.json").write_text('{"incomplete":', encoding="utf-8")

    item = build_dashboard_read_model([channel], refresh_errors={channel: "snapshot write failed"})["channels"][0]

    assert item["status"] == "ready"
    assert item["snapshot"] == "analytics_data_20260720.json"
    assert item["summary"]["views"] == 900
    assert item["refresh_error"]["code"] == "refresh_failed"


def test_read_model_does_not_modify_channel_files(tmp_path: Path) -> None:
    channel = tmp_path / "read-only"
    _write_channel(
        channel,
        name="Read Only",
        snapshots={
            "analytics_data_20260720.json": _snapshot(
                collected_at="2026-07-20T00:00:00+00:00", views=900, video_views=700
            )
        },
    )
    before = {
        path.relative_to(channel): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in channel.rglob("*")
        if path.is_file()
    }

    build_dashboard_read_model([channel])

    after = {
        path.relative_to(channel): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in channel.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_read_model_normalizes_invalid_nested_shapes_and_numeric_boundaries(tmp_path: Path) -> None:
    channel = tmp_path / "invalid-shapes"
    snapshot = _snapshot(
        collected_at="2026-07-20T00:00:00+00:00",
        views=900,
        video_views=700,
    )
    snapshot["reporting_api"]["impressions_summary"]["per_video"] = {"video-b": {"impressions": 1000}}
    snapshot["channel_analytics"]["summary"].update(
        {
            "total_views": True,
            "total_watch_time": -1,
            "net_subscribers": -4,
            "total_engagement": float("nan"),
            "avg_view_percentage": float("inf"),
        }
    )
    snapshot["scheduled_videos"]["count"] = False
    snapshot["video_analytics"]["video-b"].update(
        {
            "views": -10,
            "likes": True,
            "comments": -2,
            "shares": float("inf"),
            "subscribers_gained": -1,
            "average_view_duration": float("nan"),
        }
    )
    _write_channel(
        channel,
        name="Normalized",
        snapshots={"analytics_data_20260720.json": snapshot},
    )

    item = build_dashboard_read_model([channel])["channels"][0]

    assert item["scheduled_count"] is None
    assert item["summary"] == {
        "views": 0,
        "watch_time_minutes": 0,
        "subscribers_net": -4,
        "engagements": 0,
        "average_view_percentage": 0,
    }
    assert item["videos"][0] == {
        "video_id": "video-b",
        "title": "Later video",
        "views": 0,
        "impressions": 0,
        "ctr_percentage": 0,
        "likes": 0,
        "comments": 0,
        "shares": 0,
        "subscribers_gained": 0,
        "average_view_duration_seconds": 0,
        "engagements": 0,
    }


@pytest.mark.parametrize("channels", [None, {}, "invalid"])
def test_dashboard_api_returns_empty_channels_for_invalid_model_shape(channels: object) -> None:
    api = DashboardAPI({"schema_version": 1, "channels": channels})

    assert api.overview() == {"schema_version": 1, "channels": []}
    with pytest.raises(DashboardChannelNotFoundError):
        api.channel("unknown")


def test_dashboard_api_filters_non_object_channels_and_non_list_videos() -> None:
    api = DashboardAPI(
        {
            "schema_version": 1,
            "channels": [
                None,
                "invalid",
                {
                    "id": "valid",
                    "name": "Valid",
                    "videos": {"video": "not-a-list"},
                },
            ],
        }
    )

    assert api.overview()["channels"] == [{"id": "valid", "name": "Valid", "video_count": 0}]
    assert api.channel("valid")["videos"] == []


def test_dashboard_api_preserves_channel_without_refresh_error() -> None:
    channel = {
        "id": "legacy",
        "name": "Legacy",
        "status": "ready",
        "snapshot": None,
        "collected_at": None,
        "period": {"start_date": None, "end_date": None},
        "scheduled_count": None,
        "summary": None,
        "videos": [],
        "error": None,
    }
    api = DashboardAPI({"schema_version": 1, "channels": [channel]})

    assert api.overview() == {
        "schema_version": 1,
        "channels": [
            {
                "id": "legacy",
                "name": "Legacy",
                "status": "ready",
                "snapshot": None,
                "collected_at": None,
                "period": {"start_date": None, "end_date": None},
                "scheduled_count": None,
                "summary": None,
                "error": None,
                "video_count": 0,
            }
        ],
    }
    assert api.channel("legacy") == channel
