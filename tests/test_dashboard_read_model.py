"""Dashboard read model/API の public contract。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.utils.dashboard_read_model import DashboardAPI, build_dashboard_read_model
from youtube_automation.utils.exceptions import DashboardChannelNotFoundError


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
            "summary": {
                "total_views": views,
                "total_watch_time": 420,
                "net_subscribers": 8,
                "total_engagement": 31,
                "avg_view_percentage": 62.5,
            }
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
    assert api.channel(channel_id)["videos"][0]["video_id"] == "video-b"
    with pytest.raises(DashboardChannelNotFoundError, match="unknown"):
        api.channel("unknown")


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
