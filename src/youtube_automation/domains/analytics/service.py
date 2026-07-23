"""Injected YouTube Analytics service assembled from domain operations."""

from __future__ import annotations

from pathlib import Path

from youtube_automation.domains.analytics.collection.strategic_analytics import StrategicAnalyticsMixin
from youtube_automation.domains.analytics.collection.video_listing import VideoListingMixin
from youtube_automation.domains.analytics.mixins.audience_analytics import AudienceAnalyticsMixin
from youtube_automation.domains.analytics.mixins.channel_analytics import ChannelAnalyticsMixin
from youtube_automation.domains.analytics.mixins.ctr_analytics import CTRAnalyticsMixin
from youtube_automation.domains.analytics.mixins.playlist_analytics import PlaylistAnalyticsMixin
from youtube_automation.domains.analytics.mixins.retention_analytics import RetentionAnalyticsMixin
from youtube_automation.domains.analytics.mixins.revenue_analytics import RevenueAnalyticsMixin
from youtube_automation.domains.analytics.mixins.traffic_source_analytics import TrafficSourceMixin
from youtube_automation.domains.analytics.mixins.video_analytics import VideoAnalyticsMixin
from youtube_automation.domains.analytics.mixins.video_daily_analytics import VideoDailyAnalyticsMixin
from youtube_automation.domains.analytics.ports import AnalyticsClient, ReportingClient, YouTubeClient
from youtube_automation.domains.analytics.reporting.reporting_analytics import ReportingAPIMixin
from youtube_automation.utils.exceptions import YouTubeAPIError


class YouTubeAnalyticsCollector(
    ChannelAnalyticsMixin,
    VideoListingMixin,
    VideoAnalyticsMixin,
    VideoDailyAnalyticsMixin,
    StrategicAnalyticsMixin,
    CTRAnalyticsMixin,
    PlaylistAnalyticsMixin,
    ReportingAPIMixin,
    AudienceAnalyticsMixin,
    RetentionAnalyticsMixin,
    RevenueAnalyticsMixin,
    TrafficSourceMixin,
):
    """Coordinate analytics operations with clients supplied by the adapter."""

    def __init__(
        self,
        *,
        youtube_client: YouTubeClient,
        analytics_client: AnalyticsClient,
        reporting_client: ReportingClient,
        channel_root: Path,
    ) -> None:
        self.youtube_service = youtube_client
        self.analytics_service = analytics_client
        self.reporting_client = reporting_client
        self.channel_root = channel_root
        self.channel_id: str | None = None

    def initialize(self) -> None:
        response = self.youtube_service.resolve_channel()
        if not response:
            raise YouTubeAPIError("YouTube channel was not found")
        self.channel_id = response["id"]
