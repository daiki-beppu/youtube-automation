"""ChannelAnalyticsMixin の audience 収集配線テスト。"""

from __future__ import annotations

import pytest

from youtube_automation.utils.channel_analytics import ChannelAnalyticsMixin
from youtube_automation.utils.exceptions import YouTubeAPIError


class StubCollector(ChannelAnalyticsMixin):
    """外部 API を使わず collect_basic_analytics の公開経路を検証する。"""

    def __init__(self) -> None:
        self.called: list[str] = []

    def initialize(self) -> None:
        self.called.append("initialize")

    def get_channel_analytics(self, start_date: str, end_date: str) -> dict:
        return {"period": f"{start_date} to {end_date}"}

    def get_strategic_video_analytics(self, start_date: str, end_date: str, mode: str = "efficient") -> dict:
        return {"mode": mode, "top_videos": [], "recent_videos": [], "summary": {}}

    def _build_publish_at_map(self) -> dict[str, str]:
        return {}

    def get_scheduled_video_count(self) -> int:
        return 0

    def get_revenue_analytics(self, start_date: str, end_date: str) -> dict:
        return {"status": "available", "daily_metrics": [], "by_video": {}, "summary": {}}

    def get_ctr_analysis(self, start_date: str, end_date: str) -> dict:
        self.called.append("ctr")
        return {"source": "ctr"}

    def get_traffic_source_analytics(self, start_date: str, end_date: str) -> dict:
        self.called.append("traffic")
        return {"source": "traffic"}

    def get_traffic_source_detail(self, start_date: str, end_date: str, source_type: str) -> list[dict]:
        self.called.append("traffic_detail")
        return []

    def get_device_analytics(self, start_date: str, end_date: str) -> dict:
        self.called.append("device")
        return {"source": "device"}

    def get_playlist_analytics(self, start_date: str, end_date: str) -> dict:
        self.called.append("playlist")
        return {"playlists": {}, "total_views": 0}

    def get_subscribed_status_analytics(self, start_date: str, end_date: str) -> dict:
        self.called.append("subscribed_status")
        return {"source": "subscribed_status"}

    def get_country_analytics(self, start_date: str, end_date: str) -> dict:
        self.called.append("country")
        return {"source": "country"}

    def get_retention_summary(self, start_date: str, end_date: str, top_n: int) -> dict:
        self.called.append("retention")
        return {"source": "retention"}


@pytest.mark.parametrize("depth", ["standard", "full"])
def test_standard_and_full_depth_save_subscribed_status_audience(depth: str) -> None:
    """標準収集の公開経路が subscribedStatus 集計を JSON データへ配線する。"""
    collector = StubCollector()

    result = collector.collect_basic_analytics("2026-01-01", "2026-04-01", depth=depth)

    assert result["audience"]["by_subscribed_status"] == {"source": "subscribed_status"}
    assert result["scheduled_videos"] == {"count": 0}
    assert "subscribed_status" in collector.called
    if depth == "full":
        assert result["audience"]["by_country"] == {"source": "country"}
        assert result["retention"] == {"source": "retention"}


def test_basic_depth_keeps_existing_behavior_without_audience_collection() -> None:
    """basic 深度では audience の追加 API 呼び出しをしない。"""
    collector = StubCollector()

    result = collector.collect_basic_analytics("2026-01-01", "2026-04-01", depth="basic")

    assert "audience" not in result
    assert collector.called == ["initialize"]


def test_subscribed_status_error_fails_collection() -> None:
    """必須の登録ステータス集計が失敗した収集結果を成功扱いしない。"""
    collector = StubCollector()
    collector.get_subscribed_status_analytics = lambda start_date, end_date: {"error": "quota exceeded"}

    with pytest.raises(YouTubeAPIError, match="登録ステータス分析取得失敗: quota exceeded"):
        collector.collect_basic_analytics("2026-01-01", "2026-04-01", depth="standard")
