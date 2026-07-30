from datetime import datetime, timezone

import pytest

from youtube_automation.utils.youtube_quota import (
    DAILY_BUCKET_LIMITS,
    UNIT_COSTS,
    UNIT_POOL_LIMIT,
    complete_collection_quota_plan,
    quota_shortages,
)


def test_official_2026_quota_values_and_complete_collection_plan() -> None:
    plan = complete_collection_quota_plan()

    assert DAILY_BUCKET_LIMITS == {"videos.insert": 100, "search.list": 100}
    assert UNIT_POOL_LIMIT == 10_000
    assert UNIT_COSTS["videos.insert"] == 1
    assert UNIT_COSTS["search.list"] == 1
    assert UNIT_COSTS["thumbnails.set"] == 50
    assert UNIT_COSTS["playlistItems.insert"] == 50
    assert plan.bucket_calls == {"videos.insert": 1, "search.list": 2}
    assert plan.unit_pool_units == 102


def test_complete_collection_quota_plan_accepts_zero_playlist_inserts() -> None:
    plan = complete_collection_quota_plan(playlist_inserts=0)

    assert "playlistItems.insert" not in plan.unit_pool_calls
    assert plan.unit_pool_units == 52


def test_complete_collection_quota_plan_rejects_negative_playlist_inserts() -> None:
    with pytest.raises(ValueError, match="playlist_inserts must be >= 0"):
        complete_collection_quota_plan(playlist_inserts=-1)


def test_quota_preflight_reports_each_exhausted_pool() -> None:
    today = "2026-07-23T12:00:00+00:00"
    entries = [
        *[
            {"timestamp": today, "service": "youtube-data-api", "bucket": "videos.insert", "units": 1}
            for _ in range(100)
        ],
        *[{"timestamp": today, "service": "youtube-data-api", "bucket": "search.list", "units": 1} for _ in range(99)],
        {
            "timestamp": today,
            "service": "youtube-data-api",
            "bucket": "videos.update",
            "units": 9_950,
        },
    ]

    shortages = quota_shortages(
        complete_collection_quota_plan(),
        entries,
        now=datetime(2026, 7, 23, 13, tzinfo=timezone.utc),
    )

    assert any(message.startswith("videos.insert:") for message in shortages)
    assert any(message.startswith("search.list:") for message in shortages)
    assert any(message.startswith("unit pool:") for message in shortages)


def test_quota_preflight_ignores_previous_pacific_day() -> None:
    entries = [
        {
            "timestamp": "2026-07-23T06:59:59+00:00",
            "service": "youtube-data-api",
            "bucket": "videos.insert",
            "units": 1,
        }
        for _ in range(100)
    ]

    assert (
        quota_shortages(
            complete_collection_quota_plan(),
            entries,
            now=datetime(2026, 7, 23, 8, tzinfo=timezone.utc),
        )
        == []
    )


def test_quota_preflight_ignores_invalid_timestamps_and_other_services() -> None:
    entries = [
        {
            "timestamp": "not-a-timestamp",
            "service": "youtube-data-api",
            "bucket": "videos.insert",
            "units": 1,
        },
        *[
            {
                "timestamp": "2026-07-23T12:00:00+00:00",
                "service": "youtube-analytics-api",
                "bucket": "videos.insert",
                "units": 1,
            }
            for _ in range(100)
        ],
    ]

    assert (
        quota_shortages(
            complete_collection_quota_plan(),
            entries,
            now=datetime(2026, 7, 23, 13, tzinfo=timezone.utc),
        )
        == []
    )
