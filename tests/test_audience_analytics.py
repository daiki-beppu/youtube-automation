"""
AudienceAnalyticsMixin のユニットテスト

テスト対象: utils/audience_analytics.py
"""

import logging
from unittest.mock import MagicMock

import pytest

from youtube_automation.domains.analytics.mixins.audience_analytics import AudienceAnalyticsMixin
from youtube_automation.utils.exceptions import YouTubeAPIError


class StubCollector(AudienceAnalyticsMixin):
    def __init__(self):
        self.analytics_service = MagicMock()
        self.channel_id = "UC_TEST"

    def initialize(self):
        pass


@pytest.fixture
def collector():
    return StubCollector()


class TestGetDeviceAnalytics:
    def test_consumes_adapter_response_through_analytics_entrypoint(self, collector):
        request = collector.analytics_service.query
        request.return_value = {"rows": [["MOBILE", 1, 2, 3]]}

        result = collector.get_device_analytics("2026-01-01", "2026-04-01")

        assert result["devices"]["MOBILE"]["views"] == 1
        request.assert_called_once()

    def test_permanent_api_failure_keeps_api_specific_fail_soft_result(self, collector, caplog):
        permanent = YouTubeAPIError("forbidden", status_code=403)
        collector.analytics_service.query.side_effect = permanent

        with caplog.at_level(logging.ERROR):
            result = collector.get_device_analytics("2026-01-01", "2026-04-01")

        assert result["devices"] == {}
        assert "YouTube API エラー（デバイス分析）" in caplog.text

    def test_returns_devices_with_share(self, collector):
        """デバイス別データとシェアが正しく返る"""
        mock_response = {
            "rows": [
                ["MOBILE", 500, 2000, 120],
                ["DESKTOP", 300, 1800, 180],
                ["TV", 100, 600, 200],
            ]
        }
        collector.analytics_service.query.return_value = mock_response

        result = collector.get_device_analytics("2026-01-01", "2026-04-01")

        assert result["total_views"] == 900
        assert result["devices"]["MOBILE"]["views"] == 500
        assert result["devices"]["MOBILE"]["view_share_percent"] == pytest.approx(55.6, abs=0.1)


class TestGetCountryAnalytics:
    def test_returns_countries_with_subscribers(self, collector):
        """地域別データが subscribers_gained を含む"""
        mock_response = {
            "rows": [
                ["US", 200, 1000, 120, 5],
                ["JP", 150, 800, 150, 3],
            ]
        }
        collector.analytics_service.query.return_value = mock_response

        result = collector.get_country_analytics("2026-01-01", "2026-04-01")

        assert result["total_views"] == 350
        assert result["countries"]["JP"]["subscribers_gained"] == 3
        assert result["countries"]["US"]["view_share_percent"] == pytest.approx(57.1, abs=0.1)


class TestGetSubscribedStatusAnalytics:
    def test_mixin_docstring_includes_subscribed_status_analysis(self) -> None:
        """公開 Mixin の責務が登録ステータス分析を含む。"""
        assert AudienceAnalyticsMixin.__doc__ is not None
        assert "登録ステータス" in AudienceAnalyticsMixin.__doc__

    def test_returns_statuses_with_share_and_uses_subscribed_status_dimension(self, collector):
        """登録済み／未登録のデータ、比率、API dimension を正しく扱う"""
        collector.analytics_service.query.return_value = {
            "rows": [
                ["SUBSCRIBED", 300, 1200, 240],
                ["UNSUBSCRIBED", 700, 2800, 180],
            ]
        }

        result = collector.get_subscribed_status_analytics("2026-01-01", "2026-04-01")

        assert result == {
            "statuses": {
                "SUBSCRIBED": {
                    "views": 300,
                    "watch_time_minutes": 1200,
                    "avg_view_duration": 240,
                    "view_share_percent": 30.0,
                },
                "UNSUBSCRIBED": {
                    "views": 700,
                    "watch_time_minutes": 2800,
                    "avg_view_duration": 180,
                    "view_share_percent": 70.0,
                },
            },
            "total_views": 1000,
        }
        query_kwargs = collector.analytics_service.query.call_args.kwargs
        assert query_kwargs["dimensions"] == "subscribedStatus"
        assert query_kwargs["metrics"] == "views,estimatedMinutesWatched,averageViewDuration"

    def test_consumes_adapter_response(self, collector):
        request = collector.analytics_service.query
        request.return_value = {"rows": [["SUBSCRIBED", 1, 2, 3]]}

        result = collector.get_subscribed_status_analytics("2026-01-01", "2026-04-01")

        assert result["statuses"]["SUBSCRIBED"]["views"] == 1
        request.assert_called_once()

    def test_returns_empty_statuses_when_api_returns_no_rows(self, collector):
        """行がない API 応答は空のステータス集計として保存可能にする"""
        collector.analytics_service.query.return_value = {}

        result = collector.get_subscribed_status_analytics("2026-01-01", "2026-04-01")

        assert result == {"statuses": {}, "total_views": 0}

    def test_returns_error_shape_for_http_error(self, collector):
        """API エラーは既存 audience 集計と同じ error 付きの空データにする"""
        error = YouTubeAPIError("backendError")
        collector.analytics_service.query.side_effect = error

        result = collector.get_subscribed_status_analytics("2026-01-01", "2026-04-01")

        assert result["statuses"] == {}
        assert result["total_views"] == 0
        assert str(error) in result["error"]
