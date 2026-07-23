"""CTR 分析ロジックのユニットテスト。

YouTube Analytics API の仕様 (`videoThumbnailImpressions*` は
`dimensions=video` と組み合わせ不可) に従ったクエリ送信と、
動画別 row が [video_id, views, likes, comments, watch_time] の 5 列で処理されることを検証する。
"""

from unittest.mock import MagicMock

from youtube_automation.domains.analytics.mixins.ctr_analytics import CTRAnalyticsMixin


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
    mock_service.query.return_value = {"rows": []}
    collector = DummyCollector(mock_service)

    collector._fetch_video_ctr("2026-04-01", "2026-04-30")

    last_call_kwargs = mock_service.query.call_args.kwargs
    assert "videoThumbnailImpressions" not in last_call_kwargs["metrics"]
    assert last_call_kwargs["dimensions"] == "video"
    assert "views" in last_call_kwargs["metrics"]


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


def test_get_ctr_analysis_returns_without_impressions_summary():
    """get_ctr_analysis は動画別クエリの impressions 除外修正を経由し、
    impressions_summary キーは含まない（API 側で取れないため収集しない）。
    """
    mock_service = MagicMock()

    def execute_side_effect():
        return execute_side_effect.responses.pop(0)

    # 呼び出し順: overall / video_ctr / traffic
    execute_side_effect.responses = [
        # overall (views,likes,comments,shares,subscribersGained)
        {"rows": [[10000, 500, 100, 20, 50]]},
        # video_ctr
        {"rows": [["vid_A", 5000, 200, 30, 12000]]},
        # traffic (views,estimatedMinutesWatched dimensions=day)
        {"rows": [["2026-04-01", 300, 1200]]},
    ]
    mock_service.query.side_effect = lambda **kwargs: execute_side_effect()

    collector = DummyCollector(mock_service)
    result = collector.get_ctr_analysis("2026-04-01", "2026-04-30")

    assert "error" not in result
    assert "impressions_summary" not in result
    assert result["video_performance"][0]["video_id"] == "vid_A"
