"""benchmark_analyzer のユニットテスト"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.benchmark_analyzer import (
    compute_daily_views,
    compute_engagement_rate,
    compute_posting_intervals,
    extract_description_keywords,
    parse_iso_duration,
)


class TestParseIsoDuration:
    def test_hours_and_minutes(self):
        assert parse_iso_duration("PT2H1M30S") == "2h01m"

    def test_hours_only(self):
        assert parse_iso_duration("PT3H") == "3h00m"

    def test_minutes_only(self):
        assert parse_iso_duration("PT45M") == "45m"

    def test_seconds_only(self):
        assert parse_iso_duration("PT53S") == "53s"

    def test_hours_minutes_no_seconds(self):
        assert parse_iso_duration("PT1H30M") == "1h30m"

    def test_invalid_format(self):
        assert parse_iso_duration("invalid") == "invalid"


class TestComputeDailyViews:
    def test_basic(self):
        video = {"published_at": "2026-03-01", "views": 1000}
        result = compute_daily_views(video, today=date(2026, 3, 11))
        assert result == 100.0

    def test_same_day(self):
        video = {"published_at": "2026-03-07", "views": 500}
        result = compute_daily_views(video, today=date(2026, 3, 7))
        assert result == 500.0  # days=0 → 1に補正

    def test_fractional(self):
        video = {"published_at": "2026-03-01", "views": 333}
        result = compute_daily_views(video, today=date(2026, 3, 4))
        assert result == 111.0


class TestComputeEngagementRate:
    def test_basic(self):
        video = {"views": 1000, "likes": 50, "comments": 10}
        assert compute_engagement_rate(video) == 6.0

    def test_zero_views(self):
        video = {"views": 0, "likes": 0, "comments": 0}
        assert compute_engagement_rate(video) == 0.0

    def test_missing_fields(self):
        video = {"views": 100}
        assert compute_engagement_rate(video) == 0.0


class TestComputePostingIntervals:
    def test_regular_intervals(self):
        videos = [
            {"published_at": "2026-03-07"},
            {"published_at": "2026-03-04"},
            {"published_at": "2026-03-01"},
            {"published_at": "2026-02-26"},
            {"published_at": "2026-02-23"},
        ]
        result = compute_posting_intervals(videos)
        assert result["intervals_days"] == [3, 3, 3, 3]
        assert result["average_interval"] == 3.0
        assert result["trend"] == "stable"

    def test_accelerating(self):
        videos = [
            {"published_at": "2026-03-10"},
            {"published_at": "2026-03-08"},  # 2d
            {"published_at": "2026-03-06"},  # 2d
            {"published_at": "2026-03-01"},  # 5d
            {"published_at": "2026-02-24"},  # 5d
        ]
        result = compute_posting_intervals(videos)
        assert result["trend"] == "accelerating"

    def test_single_video(self):
        result = compute_posting_intervals([{"published_at": "2026-03-07"}])
        assert result["intervals_days"] == []
        assert result["trend"] == "stable"


class TestExtractDescriptionKeywords:
    def test_hashtags(self):
        desc = "Beautiful #celtic #fantasy music for relaxation"
        result = extract_description_keywords(desc)
        assert "celtic" in result
        assert "fantasy" in result

    def test_genre_keywords(self):
        desc = "A peaceful ambient track with harp and flute in a forest setting"
        result = extract_description_keywords(desc)
        assert "ambient" in result
        assert "harp" in result
        assert "flute" in result
        assert "forest" in result

    def test_url_removal(self):
        desc = "Check out https://example.com for more celtic music"
        result = extract_description_keywords(desc)
        assert "celtic" in result
        # URL should not produce keywords
        assert "example" not in result

    def test_dedup(self):
        desc = "#Celtic celtic CELTIC music"
        result = extract_description_keywords(desc)
        assert result.count("celtic") == 1

    def test_max_limit(self):
        # Should not exceed 20
        desc = " ".join(f"#{w}" for w in ["word"] * 30)
        result = extract_description_keywords(desc)
        assert len(result) <= 20
