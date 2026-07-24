"""収益メトリクスの収集と graceful skip の契約テスト。"""

import logging
from unittest.mock import MagicMock

from youtube_automation.infrastructure.errors import YouTubeAPIError
from youtube_automation.utils.revenue_analytics import RevenueAnalyticsMixin


class DummyCollector(RevenueAnalyticsMixin):
    def __init__(self, analytics_service):
        self.analytics_service = analytics_service
        self.channel_id = "UC_TEST"

    def initialize(self):  # type: ignore[override]
        pass


def test_collects_daily_and_video_revenue_metrics():
    service = MagicMock()
    service.reports().query().execute.side_effect = [
        {
            "currency": "USD",
            "rows": [
                ["2026-07-01", 2000, 10.0, 1000, 12.5, 10.0],
                ["2026-07-02", 3000, 21.0, 1500, 14.0, 12.0],
            ],
        },
        {"rows": [["video-1", 1000, 8.0, 600, 13.0, 11.0]]},
    ]
    service.reports().query.reset_mock()

    result = DummyCollector(service).get_revenue_analytics("2026-07-01", "2026-07-02")

    assert result["status"] == "available"
    assert result["currency"] == "USD"
    assert result["daily_metrics"][0]["estimated_revenue"] == 10.0
    assert result["daily_metrics"][0]["rpm"] == 5.0
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
    assert service.reports().query.call_args_list[0].kwargs["metrics"] == (
        "views,estimatedRevenue,monetizedPlaybacks,cpm,playbackBasedCpm"
    )


def test_monetary_api_failure_warns_and_returns_unavailable(caplog):
    service = MagicMock()
    service.reports().query().execute.side_effect = YouTubeAPIError(
        "monetary data forbidden", status_code=403, reason="forbidden"
    )

    with caplog.at_level(logging.WARNING):
        result = DummyCollector(service).get_revenue_analytics("2026-07-01", "2026-07-02")

    assert result["status"] == "unavailable"
    assert result["daily_metrics"] == []
    assert result["by_video"] == {}
    assert "基本メトリクスの収集は継続" in caplog.text
