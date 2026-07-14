"""
AudienceAnalyticsMixin のユニットテスト

テスト対象: utils/audience_analytics.py
"""

import logging
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from youtube_automation.utils.audience_analytics import AudienceAnalyticsMixin


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
    def test_retries_transient_api_failure_through_analytics_entrypoint(self, collector, monkeypatch):
        monkeypatch.setattr("youtube_automation.utils.retry.time.sleep", lambda _: None)
        transient = HttpError(Response({"status": "503"}), b'{"error": {"errors": [{"reason": "backendError"}]}}')
        request = collector.analytics_service.reports().query()
        request.execute.side_effect = [transient, {"rows": [["MOBILE", 1, 2, 3]]}]

        result = collector.get_device_analytics("2026-01-01", "2026-04-01")

        assert result["devices"]["MOBILE"]["views"] == 1
        assert request.execute.call_count == 2

    def test_permanent_api_failure_keeps_api_specific_fail_soft_result(self, collector, caplog):
        permanent = HttpError(Response({"status": "403"}), b'{"error": {"errors": [{"reason": "forbidden"}]}}')
        collector.analytics_service.reports().query().execute.side_effect = permanent

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
        collector.analytics_service.reports().query().execute.return_value = mock_response

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
        collector.analytics_service.reports().query().execute.return_value = mock_response

        result = collector.get_country_analytics("2026-01-01", "2026-04-01")

        assert result["total_views"] == 350
        assert result["countries"]["JP"]["subscribers_gained"] == 3
        assert result["countries"]["US"]["view_share_percent"] == pytest.approx(57.1, abs=0.1)
