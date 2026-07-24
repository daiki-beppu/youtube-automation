"""PlaylistAnalyticsMixin と standard/full 収集配線のテスト。"""

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from youtube_automation.infrastructure.errors import YouTubeAPIError
from youtube_automation.utils.analytics_collector import YouTubeAnalyticsCollector
from youtube_automation.utils.channel_analytics import ChannelAnalyticsMixin
from youtube_automation.utils.playlist_analytics import PlaylistAnalyticsMixin


class StubCollector(PlaylistAnalyticsMixin):
    def __init__(self):
        self.analytics_service = MagicMock()
        self.channel_id = "UC_TEST"

    def initialize(self):
        pass


@pytest.fixture
def collector():
    return StubCollector()


class TestGetPlaylistAnalytics:
    def test_queries_top_playlists_report_and_returns_mapped_metrics_with_share(self, collector):
        collector.analytics_service.reports().query().execute.return_value = {
            "rows": [
                ["PL_COMPLETE", 300, 120],
                ["PL_MIX", 200, 90],
            ]
        }
        collector.analytics_service.reports().query.reset_mock()

        result = collector.get_playlist_analytics("2026-01-01", "2026-04-01")

        collector.analytics_service.reports().query.assert_called_once_with(
            ids="channel==UC_TEST",
            startDate="2026-01-01",
            endDate="2026-04-01",
            metrics="playlistViews,playlistAverageViewDuration",
            dimensions="playlist",
            sort="-playlistViews",
            maxResults=200,
        )
        assert result == {
            "playlists": {
                "PL_COMPLETE": {
                    "views": 300,
                    "average_view_duration": 120,
                    "view_share_percent": 60.0,
                },
                "PL_MIX": {
                    "views": 200,
                    "average_view_duration": 90,
                    "view_share_percent": 40.0,
                },
            },
            "total_views": 500,
        }

    def test_returns_empty_metrics_when_api_has_no_rows(self, collector):
        collector.analytics_service.reports().query().execute.return_value = {}

        result = collector.get_playlist_analytics("2026-01-01", "2026-04-01")

        assert result == {"playlists": {}, "total_views": 0}

    def test_initializes_before_query_when_service_is_unavailable(self, collector):
        def initialize():
            collector.analytics_service = MagicMock()
            collector.analytics_service.reports().query().execute.return_value = {}

        collector.analytics_service = None
        collector.initialize = MagicMock(side_effect=initialize)

        result = collector.get_playlist_analytics("2026-01-01", "2026-04-01")

        collector.initialize.assert_called_once()
        assert result == {"playlists": {}, "total_views": 0}

    def test_raises_domain_error_when_api_request_fails(self, collector):
        collector.analytics_service.reports().query().execute.side_effect = HttpError(
            MagicMock(status=403), b"quotaExceeded"
        )

        with pytest.raises(YouTubeAPIError, match="プレイリスト分析") as error:
            collector.get_playlist_analytics("2026-01-01", "2026-04-01")

        assert error.value.status_code == 403


class TestPlaylistCollectionIntegration:
    def test_standard_depth_documentation_includes_playlist(self):
        assert "+ impressions/CTR + traffic source + playlist + device" in (
            ChannelAnalyticsMixin.collect_basic_analytics.__doc__ or ""
        )

    @pytest.mark.parametrize("depth", ["standard", "full"])
    def test_standard_and_full_collection_include_playlist_analytics(self, depth):
        collector = YouTubeAnalyticsCollector()
        collector.analytics_service = MagicMock()
        collector.channel_id = "UC_TEST"
        collector.initialize = MagicMock()
        collector.get_channel_analytics = MagicMock(return_value={"summary": {}})
        collector.get_strategic_video_analytics = MagicMock(
            return_value={"top_videos": [], "recent_videos": [], "mode": "efficient", "summary": {}}
        )
        collector.get_revenue_analytics = MagicMock(
            return_value={"status": "available", "daily_metrics": [], "by_video": {}, "summary": {}}
        )
        collector.get_subscribed_status_analytics = MagicMock(return_value={"statuses": {}, "total_views": 0})
        collector._build_publish_at_map = MagicMock(return_value={})
        collector.get_scheduled_video_count = MagicMock(return_value=0)
        collector.get_ctr_analysis = MagicMock(return_value={})
        collector.get_traffic_source_analytics = MagicMock(return_value={})
        collector.get_device_analytics = MagicMock(return_value={})
        collector.get_country_analytics = MagicMock(return_value={})
        collector.get_retention_summary = MagicMock(return_value=[])
        collector.analytics_service.reports().query().execute.return_value = {"rows": [["PL_COMPLETE", 300, 120]]}

        result = collector.collect_basic_analytics("2026-01-01", "2026-04-01", depth=depth)

        assert result["playlist_analytics"] == {
            "playlists": {
                "PL_COMPLETE": {
                    "views": 300,
                    "average_view_duration": 120,
                    "view_share_percent": 100.0,
                }
            },
            "total_views": 300,
        }

    def test_basic_collection_excludes_playlist_analytics(self):
        collector = YouTubeAnalyticsCollector()
        collector.initialize = MagicMock()
        collector.get_channel_analytics = MagicMock(return_value={"summary": {}})
        collector.get_strategic_video_analytics = MagicMock(
            return_value={"top_videos": [], "recent_videos": [], "mode": "efficient", "summary": {}}
        )
        collector.get_revenue_analytics = MagicMock(
            return_value={"status": "available", "daily_metrics": [], "by_video": {}, "summary": {}}
        )
        collector._build_publish_at_map = MagicMock(return_value={})
        collector.get_scheduled_video_count = MagicMock(return_value=0)
        collector.get_playlist_analytics = MagicMock()

        result = collector.collect_basic_analytics("2026-01-01", "2026-04-01", depth="basic")

        assert "playlist_analytics" not in result
        collector.get_playlist_analytics.assert_not_called()
