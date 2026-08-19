from unittest.mock import MagicMock

import pytest

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.analytics.mixins.video_daily_analytics import VideoDailyAnalyticsMixin


class DummyCollector(VideoDailyAnalyticsMixin):
    def __init__(self, analytics_service):
        self.analytics_service = analytics_service
        self.channel_id = "UC_TEST"


def test_get_video_daily_analytics_parses_views_only_rows():
    """YouTube Analytics API 仕様上、dimensions=video,day では
    videoThumbnailImpressions* が取得不可のため、views のみを扱う。
    """
    mock_service = MagicMock()
    mock_service.query.return_value = {
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


def test_get_video_daily_analytics_query_uses_engaged_views_metric_only():
    """クエリ送信時に videoThumbnailImpressions* が含まれないことを検証。"""
    mock_service = MagicMock()
    mock_service.query.return_value = {"rows": []}
    collector = DummyCollector(mock_service)
    collector.get_video_daily_analytics("2026-04-01", "2026-04-02")

    # reports().query(...) の最後の呼び出しを取得
    last_call_kwargs = mock_service.query.call_args.kwargs
    assert last_call_kwargs["metrics"] == "engagedViews"
    assert "videoThumbnailImpressions" not in last_call_kwargs["metrics"]


@pytest.mark.parametrize(
    ("video_ids", "expected_filter"),
    [
        (["vid_A", "vid_B"], "video==vid_A,vid_B"),
        (None, None),
        ([], None),
    ],
)
def test_get_video_daily_analytics_filter_boundary(video_ids, expected_filter):
    mock_service = MagicMock()
    mock_service.query.return_value = {}
    collector = DummyCollector(mock_service)

    result = collector.get_video_daily_analytics("2026-04-01", "2026-04-02", video_ids=video_ids)

    assert result == []
    kwargs = mock_service.query.call_args.kwargs
    if expected_filter is None:
        assert "filters" not in kwargs
    else:
        assert kwargs["filters"] == expected_filter


def test_parse_video_daily_rows_ignores_short_rows():
    assert VideoDailyAnalyticsMixin._parse_video_daily_rows(
        {"rows": [[], ["vid_A"], ["vid_A", "2026-04-01"], ["vid_B", "2026-04-02", 10]]}
    ) == [{"video_id": "vid_B", "date": "2026-04-02", "views": 10}]


def test_get_video_daily_analytics_converts_permanent_http_error():
    mock_service = MagicMock()
    mock_service.query.side_effect = YouTubeAPIError("metric not found", status_code=400)
    collector = DummyCollector(mock_service)
    with pytest.raises(YouTubeAPIError) as raised:
        collector.get_video_daily_analytics("2026-04-01", "2026-04-01", video_ids=["vid_A"])
    assert raised.value.status_code == 400
