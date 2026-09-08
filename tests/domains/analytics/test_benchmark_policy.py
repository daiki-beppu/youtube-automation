"""Provider-neutral benchmark video policy boundaries."""

from __future__ import annotations

import pytest

from youtube_automation.domains.analytics.benchmark import (
    is_live_benchmark_video,
    is_short_benchmark_duration,
    is_short_benchmark_video,
    select_top_vod_benchmark_videos,
    summarize_benchmark_videos,
)


@pytest.mark.parametrize(
    ("duration_iso", "expected"),
    [
        ("PT4M59S", True),
        ("PT5M", False),
        ("PT1H", False),
        ("PT0S", True),
        ("P0D", False),
        ("PT", False),
        ("PT4M59S-invalid", False),
        ("not-a-duration", False),
        ("", False),
    ],
)
def test_short_duration_boundary_and_invalid_values(duration_iso: str, expected: bool) -> None:
    assert is_short_benchmark_duration(duration_iso) is expected


def test_video_classification_handles_missing_duration_and_live_marker() -> None:
    assert is_short_benchmark_video({}) is False
    assert is_live_benchmark_video({}) is False
    assert is_live_benchmark_video({"duration_iso": "P0D"}) is True


@pytest.mark.parametrize(
    ("top", "expected_ids", "expected_live_ids"),
    [
        (0, [], []),
        (1, ["short"], ["live-first"]),
        (3, ["short", "vod", "vod-next"], ["live-first", "live-middle"]),
        (10, ["short", "vod", "vod-next"], ["live-first", "live-middle"]),
    ],
)
def test_top_vod_selection_skips_live_and_honors_limit(
    top: int,
    expected_ids: list[str],
    expected_live_ids: list[str],
) -> None:
    videos = [
        {"video_id": "live-first", "duration_iso": "P0D"},
        {"video_id": "short", "duration_iso": "PT4M59S"},
        {"video_id": "vod", "duration_iso": "PT1H"},
        {"video_id": "live-middle", "duration_iso": "P0D"},
        {"video_id": "vod-next", "duration_iso": "PT30M"},
    ]

    selected, skipped_live = select_top_vod_benchmark_videos(videos, top)

    assert [video["video_id"] for video in selected] == expected_ids
    assert [video["video_id"] for video in skipped_live] == expected_live_ids


def test_summary_uses_long_videos_for_averages_and_all_videos_for_tags() -> None:
    videos = [
        {
            "duration_iso": "PT10M",
            "views": 100,
            "daily_views": 1.25,
            "engagement_rate": 2.001,
            "tags": ["Study", "calm"],
        },
        {"duration_iso": "PT20M", "views": 201, "daily_views": 2.5, "engagement_rate": 3.01, "tags": ["CALM"]},
        {"duration_iso": "PT1M", "views": 9000, "daily_views": 999, "engagement_rate": 50, "tags": ["study", "Short"]},
    ]

    assert summarize_benchmark_videos(videos) == {
        "avg_views": 150,
        "avg_daily_views": 1.9,
        "avg_engagement_rate": 2.51,
        "top_tags": [{"tag": "study", "count": 2}, {"tag": "calm", "count": 2}, {"tag": "short", "count": 1}],
    }
    assert videos[0]["tags"] == ["Study", "calm"]


@pytest.mark.parametrize("videos", [[], [{"duration_iso": "PT1M", "tags": []}]])
def test_summary_without_long_videos_has_zero_averages(videos: list[dict]) -> None:
    assert summarize_benchmark_videos(videos) == {
        "avg_views": 0,
        "avg_daily_views": 0,
        "avg_engagement_rate": 0,
        "top_tags": [],
    }
