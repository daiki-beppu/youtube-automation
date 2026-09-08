"""収益メトリクスの収集と graceful skip の契約テスト。"""

import logging
from unittest.mock import MagicMock

import pytest

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.analytics.mixins.revenue_analytics import RevenueAnalyticsMixin
from youtube_automation.domains.analytics.service import YouTubeAnalyticsCollector


class DummyCollector(RevenueAnalyticsMixin):
    def __init__(self, analytics_service):
        self.analytics_service = analytics_service
        self.channel_id = "UC_TEST"

    def initialize(self):  # type: ignore[override]
        pass


@pytest.fixture(params=["mixin", "collector"])
def collector_factory(request, tmp_path):
    def create(service):
        if request.param == "mixin":
            return DummyCollector(service)
        collector = YouTubeAnalyticsCollector(
            youtube_client=MagicMock(),
            analytics_client=service,
            reporting_client=MagicMock(),
            channel_root=tmp_path,
        )
        collector.channel_id = "UC_TEST"
        return collector

    return create


def test_collects_daily_and_video_revenue_metrics(collector_factory):
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

    result = collector_factory(service).get_revenue_analytics("2026-07-01", "2026-07-02")

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


def test_returns_daily_metrics_as_partial_when_video_query_fails(collector_factory, caplog):
    service = MagicMock()
    service.query.side_effect = [
        {"currency": "USD", "rows": [["2026-07-01", 2000, 10.0, 1000, 2500, 12.5, 10.0]]},
        YouTubeAPIError("video query unsupported", status_code=400, reason="badRequest"),
    ]

    with caplog.at_level(logging.WARNING):
        result = collector_factory(service).get_revenue_analytics("2026-07-01", "2026-07-01")

    assert result["status"] == "partial"
    assert result["daily_metrics"][0]["estimated_revenue"] == 10.0
    assert result["by_video"] == {}
    assert result["summary"]["estimated_revenue"] == 10.0
    assert result["errors"] == {"video": "video query unsupported"}
    assert "動画別収益メトリクス" in caplog.text


def test_returns_video_metrics_as_partial_when_daily_query_fails(collector_factory, caplog):
    service = MagicMock()
    service.query.side_effect = [
        YouTubeAPIError("daily query forbidden", status_code=403, reason="forbidden"),
        {"currency": "JPY", "rows": [["video-1", 1000, 8.0, 600, 13.0, 11.0]]},
    ]

    with caplog.at_level(logging.WARNING):
        result = collector_factory(service).get_revenue_analytics("2026-07-01", "2026-07-01")

    assert result["status"] == "partial"
    assert result["currency"] == "JPY"
    assert result["daily_metrics"] == []
    assert result["by_video"]["video-1"]["estimated_revenue"] == 8.0
    assert result["summary"] == {}
    assert result["errors"] == {"day": "daily query forbidden"}
    assert "日次収益メトリクス" in caplog.text


def test_returns_unavailable_when_both_monetary_queries_fail(collector_factory, caplog):
    service = MagicMock()
    service.query.side_effect = [
        YouTubeAPIError("daily query forbidden", status_code=403, reason="forbidden"),
        YouTubeAPIError("video query unsupported", status_code=400, reason="badRequest"),
    ]

    with caplog.at_level(logging.WARNING):
        result = collector_factory(service).get_revenue_analytics("2026-07-01", "2026-07-02")

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


def test_zero_views_and_empty_responses_have_stable_available_summary(collector_factory):
    zero_service = MagicMock()
    zero_service.query.side_effect = [
        {"currency": "JPY", "rows": [["2026-07-01", 0, 0.0, 0, 3, 0.0, 0.0]]},
        {"rows": [["video-1", 0, 0.0, 0, 0.0, 0.0]]},
    ]

    zero = collector_factory(zero_service).get_revenue_analytics("2026-07-01", "2026-07-01")

    assert zero["daily_metrics"][0]["rpm"] == 0.0
    assert zero["daily_metrics"][0]["ads_per_playback"] == 0.0
    assert zero["by_video"]["video-1"]["rpm"] == 0.0
    assert zero["summary"]["rpm"] == 0.0

    empty_service = MagicMock()
    empty_service.query.side_effect = [{"currency": "USD"}, {}]
    empty = collector_factory(empty_service).get_revenue_analytics("2026-07-01", "2026-07-01")

    assert empty["status"] == "available"
    assert empty["daily_metrics"] == []
    assert empty["by_video"] == {}
    assert empty["summary"] == {
        "estimated_revenue": 0,
        "monetized_playbacks": 0,
        "views": 0,
        "rpm": 0.0,
    }


def test_queries_use_current_channel_and_dates(collector_factory):
    service = MagicMock()
    service.query.side_effect = [{}, {}]
    collector = collector_factory(service)
    collector.channel_id = "UC_CHANGED"
    collector.get_revenue_analytics("2026-08-01", "2026-08-31")
    for call in service.query.call_args_list:
        assert call.kwargs["ids"] == "channel==UC_CHANGED"
        assert call.kwargs["startDate"] == "2026-08-01"
        assert call.kwargs["endDate"] == "2026-08-31"
    assert [call.kwargs["dimensions"] for call in service.query.call_args_list] == ["day", "video"]


def test_unexpected_query_failure_propagates(collector_factory):
    service = MagicMock()
    service.query.side_effect = RuntimeError("unexpected failure")
    with pytest.raises(RuntimeError, match="unexpected failure"):
        collector_factory(service).get_revenue_analytics("2026-08-01", "2026-08-31")


def test_numeric_strings_use_dimension_specific_cpm_columns(collector_factory):
    service = MagicMock()
    service.query.side_effect = [
        {"currency": "JPY", "rows": [["2026-08-01", "100", "2.5", "20", "60", "7.5", "8.5"]]},
        {"rows": [["video-1", "200", "3.0", "30", "9.5", "10.5"]]},
    ]
    result = collector_factory(service).get_revenue_analytics("2026-08-01", "2026-08-31")
    assert result["daily_metrics"] == [
        {
            "date": "2026-08-01",
            "views": 100,
            "estimated_revenue": 2.5,
            "monetized_playbacks": 20,
            "ad_impressions": 60,
            "ads_per_playback": 3.0,
            "cpm": 7.5,
            "playback_based_cpm": 8.5,
            "rpm": 25.0,
        }
    ]
    assert result["by_video"]["video-1"] == {
        "video_id": "video-1",
        "views": 200,
        "estimated_revenue": 3.0,
        "monetized_playbacks": 30,
        "cpm": 9.5,
        "playback_based_cpm": 10.5,
        "rpm": 15.0,
    }
