from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from youtube_automation.utils.video_daily_analytics import VideoDailyAnalyticsMixin


class DummyCollector(VideoDailyAnalyticsMixin):
    def __init__(self, analytics_service):
        self.analytics_service = analytics_service
        self.channel_id = "UC_TEST"


def test_get_video_daily_analytics_parses_thumbnail_impressions_rows():
    mock_service = MagicMock()
    mock_service.reports().query().execute.return_value = {
        "rows": [
            ["vid_A", "2026-04-01", 100, 5000, 2.0],
            ["vid_A", "2026-04-02", 150, 7000, 2.1],
            ["vid_B", "2026-04-01", 200, 10000, 2.0],
        ],
    }
    collector = DummyCollector(mock_service)
    result = collector.get_video_daily_analytics("2026-04-01", "2026-04-02", video_ids=["vid_A", "vid_B"])
    assert len(result) == 3
    assert result[0] == {
        "video_id": "vid_A",
        "date": "2026-04-01",
        "views": 100,
        "impressions": 5000,
        "impression_ctr": 2.0,
    }
    assert result[2]["video_id"] == "vid_B"


def test_get_video_daily_analytics_propagates_http_error():
    mock_service = MagicMock()
    mock_service.reports().query().execute.side_effect = HttpError(MagicMock(status=400), b"metric not found")
    collector = DummyCollector(mock_service)
    with pytest.raises(HttpError):
        collector.get_video_daily_analytics("2026-04-01", "2026-04-01", video_ids=["vid_A"])
