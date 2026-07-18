"""_build_publish_at_map() のユニットテスト"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


@pytest.fixture
def live_dir(tmp_path):
    """upload_tracking.json を持つ模擬 collections/live/ を構築"""
    live = tmp_path / "collections" / "live"

    # コレクション A: 正常な tracking
    col_a = live / "20260326-rjn-cafe-collection" / "20-documentation"
    col_a.mkdir(parents=True)
    (col_a / "upload_tracking.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "collection_name": "20260326-rjn-cafe-collection",
                "status": "completed",
                "complete_collection": {
                    "video_id": "ABC123",
                    "video_url": "https://www.youtube.com/watch?v=ABC123",
                    "upload_time": "2026-03-25T08:00:00.000000",
                    "publish_at": "2026-03-26T11:00:00+09:00",
                    "status": "completed",
                },
            }
        )
    )

    # コレクション B: 正常な tracking（別タイムゾーン）
    col_b = live / "20260402-rjn-ember-collection" / "20-documentation"
    col_b.mkdir(parents=True)
    (col_b / "upload_tracking.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "collection_name": "20260402-rjn-ember-collection",
                "status": "completed",
                "complete_collection": {
                    "video_id": "DEF456",
                    "video_url": "https://www.youtube.com/watch?v=DEF456",
                    "upload_time": "2026-04-01T10:00:00.000000",
                    "publish_at": "2026-04-02T02:00:00-04:00",
                    "status": "completed",
                },
            }
        )
    )

    # コレクション C: tracking なし（planning 段階）
    col_c = live / "20260410-rjn-wip-collection" / "20-documentation"
    col_c.mkdir(parents=True)

    # コレクション D: 壊れた JSON
    col_d = live / "20260411-rjn-broken-collection" / "20-documentation"
    col_d.mkdir(parents=True)
    (col_d / "upload_tracking.json").write_text("not json")

    return tmp_path


def _make_mixin():
    """ChannelAnalyticsMixin だけをインスタンス化するヘルパー"""
    from youtube_automation.utils.channel_analytics import ChannelAnalyticsMixin

    return object.__new__(ChannelAnalyticsMixin)


class TestBuildPublishAtMap:
    def test_returns_mapping_for_valid_tracking(self, live_dir):
        mixin = _make_mixin()
        with patch("youtube_automation.utils.channel_analytics.channel_dir", return_value=live_dir):
            result = mixin._build_publish_at_map()

        assert result == {
            "ABC123": "2026-03-26T11:00:00+09:00",
            "DEF456": "2026-04-02T02:00:00-04:00",
        }

    def test_skips_missing_tracking(self, live_dir):
        """tracking ファイルがないコレクションは無視"""
        mixin = _make_mixin()
        with patch("youtube_automation.utils.channel_analytics.channel_dir", return_value=live_dir):
            result = mixin._build_publish_at_map()

        assert "WIP_ID" not in result

    def test_skips_broken_json(self, live_dir):
        """壊れた JSON は無視してクラッシュしない"""
        mixin = _make_mixin()
        with patch("youtube_automation.utils.channel_analytics.channel_dir", return_value=live_dir):
            result = mixin._build_publish_at_map()

        # 壊れた分はスキップされ、正常な2件だけ返る
        assert len(result) == 2

    def test_empty_when_no_live_dir(self, tmp_path):
        """collections/live/ が存在しない場合は空 dict"""
        mixin = _make_mixin()
        with patch("youtube_automation.utils.channel_analytics.channel_dir", return_value=tmp_path):
            result = mixin._build_publish_at_map()

        assert result == {}


class TestCollectBasicAnalyticsIntegration:
    """collect_basic_analytics() が scheduled_publish_at を注入することを検証"""

    def test_default_depth_remains_standard_without_full_only_data(self, tmp_path):
        """depth 未指定時は standard データだけを返す。"""
        mixin = _make_mixin()
        mixin.initialize = lambda: None
        mixin.get_channel_analytics = lambda s, e: {"period": "test", "daily_metrics": []}
        mixin.get_strategic_video_analytics = lambda s, e, mode="efficient": {
            "mode": "efficient",
            "top_videos": [],
            "recent_videos": [],
            "summary": {},
        }
        mixin.get_revenue_analytics = lambda s, e: {
            "status": "available",
            "daily_metrics": [],
            "by_video": {},
            "summary": {},
        }
        mixin.get_ctr_analysis = lambda s, e: {"videos": []}
        mixin.get_traffic_source_analytics = lambda s, e: {"sources": {}}
        mixin.get_traffic_source_detail = lambda s, e, source_type: []
        mixin.get_playlist_analytics = lambda s, e: {"playlists": {}, "total_views": 0}
        mixin.get_device_analytics = lambda s, e: {"devices": {}}
        mixin.get_subscribed_status_analytics = lambda s, e: {"statuses": {}, "total_views": 0}
        mixin.get_country_analytics = lambda s, e: pytest.fail("country should require full depth")
        mixin.get_retention_summary = lambda s, e, top_n: pytest.fail("retention should require full depth")

        with patch("youtube_automation.utils.channel_analytics.channel_dir", return_value=tmp_path):
            result = mixin.collect_basic_analytics("2026-03-14", "2026-04-13")

        assert result["collection_depth"] == "standard"
        assert result["summary"]["depth"] == "standard"
        assert result["audience"] == {
            "by_device": {"devices": {}},
            "by_subscribed_status": {"statuses": {}, "total_views": 0},
        }
        assert "retention" not in result

    def test_injects_scheduled_publish_at(self, live_dir):
        """video_data に scheduled_publish_at が追加される"""
        mixin = _make_mixin()
        mixin.initialize = lambda: None
        mixin.get_channel_analytics = lambda s, e: {"period": "test", "daily_metrics": []}
        mixin.get_strategic_video_analytics = lambda s, e, mode="efficient": {
            "mode": "efficient",
            "top_videos": [
                {"video_id": "ABC123", "title": "Cafe", "published_at": "2026-03-25T08:00:00Z"},
                {"video_id": "XYZ789", "title": "Unknown", "published_at": "2026-04-01T00:00:00Z"},
            ],
            "recent_videos": [],
            "summary": {},
        }
        mixin.get_revenue_analytics = lambda s, e: {
            "status": "available",
            "daily_metrics": [],
            "by_video": {"ABC123": {"estimated_revenue": 12.0, "rpm": 6.0}},
            "summary": {},
        }

        with patch("youtube_automation.utils.channel_analytics.channel_dir", return_value=live_dir):
            result = mixin.collect_basic_analytics("2026-03-14", "2026-04-13", depth="basic")

            video_data = result["video_analytics"]
            # マッチする動画: publish_at が入る
            assert video_data["ABC123"]["scheduled_publish_at"] == "2026-03-26T11:00:00+09:00"
            assert video_data["ABC123"]["estimated_revenue"] == 12.0
            assert video_data["ABC123"]["rpm"] == 6.0
            # マッチしない動画: None
            assert video_data["XYZ789"]["scheduled_publish_at"] is None
