from unittest.mock import MagicMock

import pytest

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.analytics.mixins.video_daily_analytics import VideoDailyAnalyticsMixin
from youtube_automation.domains.analytics.service import YouTubeAnalyticsCollector


class DummyCollector(VideoDailyAnalyticsMixin):
    def __init__(self, analytics_service):
        self.analytics_service = analytics_service
        self.channel_id = "UC_TEST"


@pytest.fixture(params=["mixin", "collector"])
def collector_factory(request, tmp_path):
    def create(client):
        if request.param == "mixin":
            return DummyCollector(client)
        instance = YouTubeAnalyticsCollector(
            youtube_client=MagicMock(), analytics_client=client, reporting_client=MagicMock(), channel_root=tmp_path
        )
        instance.channel_id = "UC_TEST"
        return instance

    return create


def test_get_video_daily_analytics_parses_views_only_rows(collector_factory):
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
    collector = collector_factory(mock_service)
    result = collector.get_video_daily_analytics("2026-04-01", "2026-04-02", video_ids=["vid_A", "vid_B"])
    assert len(result) == 3
    assert result[0] == {
        "video_id": "vid_A",
        "date": "2026-04-01",
        "views": 100,
    }
    assert result[2]["video_id"] == "vid_B"


def test_get_video_daily_analytics_query_uses_engaged_views_metric_only(collector_factory):
    """クエリ送信時に videoThumbnailImpressions* が含まれないことを検証。"""
    mock_service = MagicMock()
    mock_service.query.return_value = {"rows": []}
    collector = collector_factory(mock_service)
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
def test_get_video_daily_analytics_filter_boundary(collector_factory, video_ids, expected_filter):
    mock_service = MagicMock()
    mock_service.query.return_value = {}
    collector = collector_factory(mock_service)

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


def test_get_video_daily_analytics_converts_permanent_http_error(collector_factory):
    mock_service = MagicMock()
    mock_service.query.side_effect = YouTubeAPIError("metric not found", status_code=400)
    collector = collector_factory(mock_service)
    with pytest.raises(YouTubeAPIError) as raised:
        collector.get_video_daily_analytics("2026-04-01", "2026-04-01", video_ids=["vid_A"])
    assert raised.value.status_code == 400


def test_video_daily_preserves_instance_parser_override(collector_factory):
    client = MagicMock()
    response = {"rows": [["video", "2026-01-01", 10]]}
    client.query.return_value = response
    collector = collector_factory(client)
    converted = [{"custom": "row"}]
    collector._parse_video_daily_rows = MagicMock(return_value=converted)

    assert collector.get_video_daily_analytics("2026-01-01", "2026-01-02") is converted
    collector._parse_video_daily_rows.assert_called_once_with(response)
