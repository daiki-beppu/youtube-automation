from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from youtube_automation.utils.video_daily_analytics import VideoDailyAnalyticsMixin


class DummyCollector(VideoDailyAnalyticsMixin):
    def __init__(self, analytics_service):
        self.analytics_service = analytics_service
        self.channel_id = "UC_TEST"


def test_get_video_daily_analytics_parses_views_only_rows():
    """YouTube Analytics API 仕様上、dimensions=video,day では
    videoThumbnailImpressions* が取得不可のため、views のみを扱う。
    """
    mock_service = MagicMock()
    mock_service.reports().query().execute.return_value = {
        "rows": [
            ["vid_A", "2026-04-01", 100],
            ["vid_A", "2026-04-02", 150],
            ["vid_B", "2026-04-01", 200],
        ],
    }
    collector = DummyCollector(mock_service)
    result = collector.get_video_daily_analytics("2026-04-01", "2026-04-02", video_ids=["vid_A", "vid_B"])
    assert len(result) == 3
    assert result[0] == {
        "video_id": "vid_A",
        "date": "2026-04-01",
        "views": 100,
    }
    assert result[2]["video_id"] == "vid_B"


def test_get_video_daily_analytics_query_uses_views_metric_only():
    """クエリ送信時に videoThumbnailImpressions* が含まれないことを検証。"""
    mock_service = MagicMock()
    mock_service.reports().query().execute.return_value = {"rows": []}
    collector = DummyCollector(mock_service)
    collector.get_video_daily_analytics("2026-04-01", "2026-04-02")

    # reports().query(...) の最後の呼び出しを取得
    calls = mock_service.reports().query.call_args_list
    # 最後の呼び出しが実際のクエリ (最初は .query() によるチェーン構築のダミー)
    last_call_kwargs = calls[-1].kwargs
    assert last_call_kwargs["metrics"] == "views"
    assert "videoThumbnailImpressions" not in last_call_kwargs["metrics"]


def test_get_video_daily_analytics_propagates_http_error():
    mock_service = MagicMock()
    mock_service.reports().query().execute.side_effect = HttpError(MagicMock(status=400), b"metric not found")
    collector = DummyCollector(mock_service)
    with pytest.raises(HttpError):
        collector.get_video_daily_analytics("2026-04-01", "2026-04-01", video_ids=["vid_A"])
