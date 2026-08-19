"""
TrafficSourceMixin のユニットテスト

テスト対象: domains/analytics/mixins/traffic_source_analytics.py
"""

from unittest.mock import MagicMock

import pytest

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.analytics.mixins.traffic_source_analytics import TrafficSourceMixin


class StubCollector(TrafficSourceMixin):
    def __init__(self):
        self.analytics_service = MagicMock()
        self.channel_id = "UC_TEST"

    def initialize(self):
        pass


@pytest.fixture
def collector():
    return StubCollector()


class TestGetTrafficSourceAnalytics:
    def test_returns_sources_with_share(self, collector):
        """トラフィックソースとシェアが正しく計算される"""
        mock_response = {
            "rows": [
                ["YT_SEARCH", 300, 1500, 120],
                ["BROWSE", 200, 800, 90],
                ["RELATED_VIDEO", 100, 400, 80],
            ]
        }
        collector.analytics_service.query.return_value = mock_response

        result = collector.get_traffic_source_analytics("2026-01-01", "2026-04-01")

        query = collector.analytics_service.query.call_args.kwargs
        assert query["metrics"] == "engagedViews,estimatedMinutesWatched,averageViewDuration"
        assert query["sort"] == "-engagedViews"
        assert result["total_views"] == 600
        assert result["sources"]["YT_SEARCH"]["views"] == 300
        assert result["sources"]["YT_SEARCH"]["view_share_percent"] == 50.0
        assert result["sources"]["BROWSE"]["view_share_percent"] == pytest.approx(33.3, abs=0.1)

    def test_empty_response(self, collector):
        """データなしの場合"""
        collector.analytics_service.query.return_value = {}

        result = collector.get_traffic_source_analytics("2026-01-01", "2026-04-01")

        assert result["sources"] == {}
        assert result["total_views"] == 0

    def test_zero_views_and_api_failure_return_stable_shapes(self, collector):
        collector.analytics_service.query.return_value = {"rows": [["YT_SEARCH", 0, 0, 0]]}
        zero = collector.get_traffic_source_analytics("2026-01-01", "2026-04-01")
        assert zero["sources"]["YT_SEARCH"]["view_share_percent"] == 0

        collector.analytics_service.query.side_effect = YouTubeAPIError("traffic unavailable")
        failed = collector.get_traffic_source_analytics("2026-01-01", "2026-04-01")
        assert failed["sources"] == {}
        assert failed["total_views"] == 0
        assert "traffic unavailable" in failed["error"]


class TestGetTrafficSourceDetail:
    def test_returns_detail_list(self, collector):
        """検索キーワード等の詳細データが返る"""
        mock_response = {
            "rows": [
                ["lofi music", 100, 500],
                ["chiptune bgm", 50, 200],
            ]
        }
        collector.analytics_service.query.return_value = mock_response

        result = collector.get_traffic_source_detail("2026-01-01", "2026-04-01", "YT_SEARCH")

        query = collector.analytics_service.query.call_args.kwargs
        assert query["metrics"] == "engagedViews,estimatedMinutesWatched"
        assert query["sort"] == "-engagedViews"
        assert len(result) == 2
        assert result[0]["detail"] == "lofi music"
        assert result[0]["views"] == 100

    def test_api_failure_returns_empty_detail_list(self, collector):
        collector.analytics_service.query.side_effect = YouTubeAPIError("detail unavailable")

        assert collector.get_traffic_source_detail("2026-01-01", "2026-04-01", "YT_SEARCH") == []
