"""CTR 分析ロジックのユニットテスト。

YouTube Analytics API の仕様 (`videoThumbnailImpressions*` は
`dimensions=video` と組み合わせ不可) に従ったクエリ送信と、
チャンネル全体 impressions サマリーが維持されることを検証する。
"""

from unittest.mock import MagicMock

from googleapiclient.errors import HttpError

from youtube_automation.utils.ctr_analytics import CTRAnalyticsMixin


class DummyCollector(CTRAnalyticsMixin):
    def __init__(self, analytics_service):
        self.analytics_service = analytics_service
        self.channel_id = "UC_TEST"

    def initialize(self):  # type: ignore[override]
        pass

    def _get_video_details(self, video_ids):  # type: ignore[override]
        return {vid: {"title": f"title-{vid}"} for vid in video_ids}


def test_fetch_video_ctr_excludes_thumbnail_impressions_metrics():
    """動画別クエリから videoThumbnailImpressions* が除外されていること。"""
    mock_service = MagicMock()
    mock_service.reports().query().execute.return_value = {"rows": []}
    collector = DummyCollector(mock_service)

    collector._fetch_video_ctr("2026-04-01", "2026-04-30")

    last_call_kwargs = mock_service.reports().query.call_args_list[-1].kwargs
    assert "videoThumbnailImpressions" not in last_call_kwargs["metrics"]
    assert last_call_kwargs["dimensions"] == "video"
    assert "views" in last_call_kwargs["metrics"]


def test_fetch_channel_impressions_summary_uses_no_dimensions():
    """チャンネル全体 impressions サマリーは dimensions 無しで取得される。"""
    mock_service = MagicMock()
    mock_service.reports().query().execute.return_value = {"rows": []}
    collector = DummyCollector(mock_service)

    collector._fetch_channel_impressions_summary("2026-04-01", "2026-04-30")

    last_call_kwargs = mock_service.reports().query.call_args_list[-1].kwargs
    assert "videoThumbnailImpressions" in last_call_kwargs["metrics"]
    assert "videoThumbnailImpressionsClickRate" in last_call_kwargs["metrics"]
    assert "dimensions" not in last_call_kwargs


def test_process_channel_impressions_summary_builds_expected_shape():
    """チャンネル全体 impressions レスポンスが所定の dict 形に変換される。"""
    collector = DummyCollector(MagicMock())

    # row: [views, impressions, impression_ctr]
    response = {"rows": [[1000, 50000, 2.5]]}
    result = collector._process_channel_impressions_summary(response)

    assert result == {
        "total_impressions": 50000,
        "total_views_from_impressions": 1000,
        "aggregated_ctr_percentage": 2.5,
    }


def test_process_channel_impressions_summary_empty_response_returns_zeros():
    collector = DummyCollector(MagicMock())
    result = collector._process_channel_impressions_summary({"rows": []})
    assert result == {
        "total_impressions": 0,
        "total_views_from_impressions": 0,
        "aggregated_ctr_percentage": 0,
    }


def test_process_video_ctr_parses_five_column_rows():
    """動画別 row が [video_id, views, likes, comments, watch_time] の 5 列。"""
    collector = DummyCollector(MagicMock())
    response = {
        "rows": [
            ["vid_A", 1000, 50, 10, 2000],
            ["vid_B", 500, 20, 5, 800],
        ]
    }

    result = collector._process_video_ctr(response)

    assert len(result) == 2
    assert result[0] == {
        "video_id": "vid_A",
        "title": "title-vid_A",
        "views": 1000,
        "likes": 50,
        "comments": 10,
        "watch_time_minutes": 2000,
        "collection_type": "Other",
    }
    # impressions / impression_ctr は動画別クエリでは取得できないため含まれない
    assert "impressions" not in result[0]
    assert "impression_ctr" not in result[0]


def test_get_ctr_analysis_keeps_impressions_summary_via_channel_query():
    """get_ctr_analysis の戻り値に impressions_summary が含まれ、
    チャンネル全体クエリの値が入ること。
    """
    mock_service = MagicMock()

    def execute_side_effect():
        return execute_side_effect.responses.pop(0)

    # 呼び出し順: overall / video_ctr / traffic / channel_impressions
    execute_side_effect.responses = [
        # overall (views,likes,comments,shares,subscribersGained)
        {"rows": [[10000, 500, 100, 20, 50]]},
        # video_ctr
        {"rows": [["vid_A", 5000, 200, 30, 12000]]},
        # traffic (views,estimatedMinutesWatched dimensions=day)
        {"rows": [["2026-04-01", 300, 1200]]},
        # channel impressions summary (views,thumbImpressions,ctr)
        {"rows": [[10000, 400000, 2.5]]},
    ]
    mock_service.reports().query().execute.side_effect = execute_side_effect

    collector = DummyCollector(mock_service)
    result = collector.get_ctr_analysis("2026-04-01", "2026-04-30")

    assert "impressions_summary" in result
    assert result["impressions_summary"]["total_impressions"] == 400000
    assert result["impressions_summary"]["aggregated_ctr_percentage"] == 2.5
    assert "error" not in result


def test_get_ctr_analysis_tolerates_impressions_query_failure():
    """impressions クエリが 400 を返しても CTR 分析全体は成功し、
    impressions_summary は空の既定値で返る (小規模チャンネル等で発生する挙動)。
    """
    mock_service = MagicMock()

    def execute_side_effect():
        payload = execute_side_effect.responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload

    execute_side_effect.responses = [
        {"rows": [[10000, 500, 100, 20, 50]]},
        {"rows": [["vid_A", 5000, 200, 30, 12000]]},
        {"rows": [["2026-04-01", 300, 1200]]},
        HttpError(MagicMock(status=400), b"videoThumbnailImpressions unavailable"),
    ]
    mock_service.reports().query().execute.side_effect = execute_side_effect

    collector = DummyCollector(mock_service)
    result = collector.get_ctr_analysis("2026-04-01", "2026-04-30")

    assert "error" not in result
    assert result["impressions_summary"] == {
        "total_impressions": 0,
        "total_views_from_impressions": 0,
        "aggregated_ctr_percentage": 0,
    }
    # 他のメトリクスは取得できていること
    assert result["video_performance"][0]["video_id"] == "vid_A"
