"""収益メトリクスの収集と graceful skip の契約テスト。"""

import logging
from unittest.mock import MagicMock

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.analytics.mixins.revenue_analytics import RevenueAnalyticsMixin


class DummyCollector(RevenueAnalyticsMixin):
    def __init__(self, analytics_service):
        self.analytics_service = analytics_service
        self.channel_id = "UC_TEST"

    def initialize(self):  # type: ignore[override]
        pass


def test_collects_daily_and_video_revenue_metrics():
    service = MagicMock()
    service.query.side_effect = [
        {
            "currency": "USD",
            "rows": [
                ["2026-07-01", 2000, 10.0, 1000, 2500, 12.5, 10.0],
                ["2026-07-02", 3000, 21.0, 1500, 4500, 14.0, 12.0],
            ],
        },
        {"rows": [["video-1", 1000, 8.0, 600, 13.0, 11.0]]},
    ]
    service.query.reset_mock()

    result = DummyCollector(service).get_revenue_analytics("2026-07-01", "2026-07-02")

    assert result["status"] == "available"
    assert result["currency"] == "USD"
    assert result["daily_metrics"][0]["estimated_revenue"] == 10.0
    assert result["daily_metrics"][0]["rpm"] == 5.0
    assert result["daily_metrics"][0]["ad_impressions"] == 2500
    assert result["daily_metrics"][0]["ads_per_playback"] == 2.5
    assert result["by_video"]["video-1"] == {
        "video_id": "video-1",
        "views": 1000,
        "estimated_revenue": 8.0,
        "monetized_playbacks": 600,
        "cpm": 13.0,
        "playback_based_cpm": 11.0,
        "rpm": 8.0,
    }
    assert result["summary"] == {
        "estimated_revenue": 31.0,
        "monetized_playbacks": 2500,
        "views": 5000,
        "rpm": 6.2,
    }
    assert service.query.call_args_list[0].kwargs["metrics"] == (
        "engagedViews,estimatedRevenue,monetizedPlaybacks,adImpressions,cpm,playbackBasedCpm"
    )
    assert service.query.call_args_list[1].kwargs["metrics"] == (
        "engagedViews,estimatedRevenue,monetizedPlaybacks,cpm,playbackBasedCpm"
    )
    assert service.query.call_args_list[1].kwargs["maxResults"] == 200


def test_returns_daily_metrics_as_partial_when_video_query_fails(caplog):
    service = MagicMock()
    service.query.side_effect = [
        {"currency": "USD", "rows": [["2026-07-01", 2000, 10.0, 1000, 2500, 12.5, 10.0]]},
        YouTubeAPIError("video query unsupported", status_code=400, reason="badRequest"),
    ]

    with caplog.at_level(logging.WARNING):
        result = DummyCollector(service).get_revenue_analytics("2026-07-01", "2026-07-01")

    assert result["status"] == "partial"
    assert result["daily_metrics"][0]["estimated_revenue"] == 10.0
    assert result["by_video"] == {}
    assert result["summary"]["estimated_revenue"] == 10.0
    assert result["errors"] == {"video": "video query unsupported"}
    assert "動画別収益メトリクス" in caplog.text


def test_returns_video_metrics_as_partial_when_daily_query_fails(caplog):
    service = MagicMock()
    service.query.side_effect = [
        YouTubeAPIError("daily query forbidden", status_code=403, reason="forbidden"),
        {"currency": "JPY", "rows": [["video-1", 1000, 8.0, 600, 13.0, 11.0]]},
    ]

    with caplog.at_level(logging.WARNING):
        result = DummyCollector(service).get_revenue_analytics("2026-07-01", "2026-07-01")

    assert result["status"] == "partial"
    assert result["currency"] == "JPY"
    assert result["daily_metrics"] == []
    assert result["by_video"]["video-1"]["estimated_revenue"] == 8.0
    assert result["summary"] == {}
    assert result["errors"] == {"day": "daily query forbidden"}
    assert "日次収益メトリクス" in caplog.text


def test_returns_unavailable_when_both_monetary_queries_fail(caplog):
    service = MagicMock()
    service.query.side_effect = [
        YouTubeAPIError("daily query forbidden", status_code=403, reason="forbidden"),
        YouTubeAPIError("video query unsupported", status_code=400, reason="badRequest"),
    ]

    with caplog.at_level(logging.WARNING):
        result = DummyCollector(service).get_revenue_analytics("2026-07-01", "2026-07-02")

    assert result["status"] == "unavailable"
    assert result["daily_metrics"] == []
    assert result["by_video"] == {}
    assert result["errors"] == {
        "day": "daily query forbidden",
        "video": "video query unsupported",
    }
    assert result["reason"] == "day: daily query forbidden; video: video query unsupported"
    assert service.query.call_count == 2
    assert "基本メトリクスの収集は継続" in caplog.text


def test_zero_views_and_empty_responses_have_stable_available_summary():
    zero_service = MagicMock()
    zero_service.query.side_effect = [
        {"currency": "JPY", "rows": [["2026-07-01", 0, 0.0, 0, 3, 0.0, 0.0]]},
        {"rows": [["video-1", 0, 0.0, 0, 0.0, 0.0]]},
    ]

    zero = DummyCollector(zero_service).get_revenue_analytics("2026-07-01", "2026-07-01")

    assert zero["daily_metrics"][0]["rpm"] == 0.0
    assert zero["daily_metrics"][0]["ads_per_playback"] == 0.0
    assert zero["by_video"]["video-1"]["rpm"] == 0.0
    assert zero["summary"]["rpm"] == 0.0

    empty_service = MagicMock()
    empty_service.query.side_effect = [{"currency": "USD"}, {}]
    empty = DummyCollector(empty_service).get_revenue_analytics("2026-07-01", "2026-07-01")

    assert empty["status"] == "available"
    assert empty["daily_metrics"] == []
    assert empty["by_video"] == {}
    assert empty["summary"] == {
        "estimated_revenue": 0,
        "monetized_playbacks": 0,
        "views": 0,
        "rpm": 0.0,
    }
