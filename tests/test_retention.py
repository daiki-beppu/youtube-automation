"""
RetentionAnalyticsMixin のユニットテスト

テスト対象: utils/retention_analytics.py
"""

from unittest.mock import MagicMock

import pytest

from youtube_automation.infrastructure.errors import YouTubeAPIError
from youtube_automation.utils.retention_analytics import RetentionAnalyticsMixin
from youtube_automation.utils.video_analytics import VideoAnalyticsMixin


class StubCollector(RetentionAnalyticsMixin, VideoAnalyticsMixin):
    def __init__(self):
        self.analytics_service = MagicMock()
        self.youtube_service = MagicMock()
        self.channel_id = "UC_TEST"

    def initialize(self):
        pass


@pytest.fixture
def collector():
    return StubCollector()


class TestGetAudienceRetention:
    def test_returns_retention_curve(self, collector):
        """視聴維持率曲線が正しく返る"""
        mock_response = {
            "rows": [
                [0.0, 1.0, 1.2],
                [0.1, 0.9, 1.1],
                [0.5, 0.6, 0.9],
                [1.0, 0.3, 0.7],
            ]
        }
        collector.analytics_service.reports().query().execute.return_value = mock_response

        result = collector.get_audience_retention("VID_001", "2026-01-01", "2026-04-01")

        assert result["video_id"] == "VID_001"
        assert result["data_points"] == 4
        assert result["average_retention"] == pytest.approx(0.7, abs=0.01)
        assert result["midpoint_retention"] == pytest.approx(0.6, abs=0.01)

    def test_empty_response(self, collector):
        """データなしの場合"""
        collector.analytics_service.reports().query().execute.return_value = {}

        result = collector.get_audience_retention("VID_EMPTY", "2026-01-01", "2026-04-01")

        assert result["data_points"] == 0
        assert result["average_retention"] == 0


class TestGetRetentionSummary:
    def test_top_video_api_failure_is_propagated(self, collector, monkeypatch):
        """上位動画一覧の API 失敗を「対象動画なし」に変換しない。"""

        def fail_request(request, message):
            raise YouTubeAPIError(message)

        monkeypatch.setattr("youtube_automation.utils.retention_analytics.execute_with_retry", fail_request)

        with pytest.raises(YouTubeAPIError, match="YouTube Analytics API request failed"):
            collector.get_retention_summary("2026-01-01", "2026-04-01", top_n=2)

    def test_returns_sorted_by_retention(self, collector):
        """上位動画の維持率がソートされて返る"""
        # 上位動画リスト取得用のモック
        top_response = {
            "rows": [
                ["VID_A", 1000],
                ["VID_B", 500],
            ]
        }

        # 各動画の retention 用モック
        retention_a = {
            "rows": [
                [0.0, 1.0, 1.0],
                [0.5, 0.4, 0.8],
                [1.0, 0.2, 0.6],
            ]
        }
        retention_b = {
            "rows": [
                [0.0, 1.0, 1.0],
                [0.5, 0.7, 1.1],
                [1.0, 0.5, 0.9],
            ]
        }

        # reports().query().execute() を呼び出し順にモック
        collector.analytics_service.reports().query().execute.side_effect = [
            top_response,
            retention_a,
            retention_b,
        ]

        # _get_video_details のモック
        collector.youtube_service.videos().list().execute.return_value = {
            "items": [
                {
                    "id": "VID_A",
                    "snippet": {"title": "Video A", "publishedAt": "2026-01-01T00:00:00Z"},
                    "contentDetails": {},
                    "topicDetails": {},
                },
                {
                    "id": "VID_B",
                    "snippet": {"title": "Video B", "publishedAt": "2026-01-01T00:00:00Z"},
                    "contentDetails": {},
                    "topicDetails": {},
                },
            ]
        }

        result = collector.get_retention_summary("2026-01-01", "2026-04-01", top_n=2)

        assert len(result) == 2
        # VID_B (avg ~0.733) > VID_A (avg ~0.533) なので B が先
        assert result[0]["title"] == "Video B"
        assert result[0]["average_retention"] > result[1]["average_retention"]
