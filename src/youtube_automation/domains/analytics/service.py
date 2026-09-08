"""Injected YouTube Analytics service assembled from domain operations."""

from __future__ import annotations

from pathlib import Path

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.analytics.collection.strategic_analytics import StrategicAnalyticsMixin
from youtube_automation.domains.analytics.mixins.audience_analytics import (
    collect_country_analytics,
    collect_device_analytics,
    collect_subscribed_status_analytics,
)
from youtube_automation.domains.analytics.mixins.channel_analytics import ChannelAnalyticsMixin
from youtube_automation.domains.analytics.mixins.ctr_analytics import CTRAnalyticsMixin
from youtube_automation.domains.analytics.mixins.playlist_analytics import (
    collect_playlist_analytics,
)
from youtube_automation.domains.analytics.mixins.retention_analytics import (
    collect_audience_retention,
    collect_retention_summary,
)
from youtube_automation.domains.analytics.mixins.revenue_analytics import collect_revenue_analytics
from youtube_automation.domains.analytics.mixins.traffic_source_analytics import (
    collect_traffic_source_details,
    collect_traffic_sources,
)
from youtube_automation.domains.analytics.mixins.video_analytics import VideoAnalyticsMixin
from youtube_automation.domains.analytics.mixins.video_daily_analytics import (
    collect_video_daily_analytics,
    parse_video_daily_rows,
)
from youtube_automation.domains.analytics.ports import AnalyticsClient, ReportingClient, YouTubeClient
from youtube_automation.domains.analytics.reporting.reporting_analytics import collect_reporting_impressions
from youtube_automation.domains.youtube.video_listing import VideoListingMixin


class YouTubeAnalyticsCollector(
    ChannelAnalyticsMixin,
    VideoListingMixin,
    VideoAnalyticsMixin,
    StrategicAnalyticsMixin,
    CTRAnalyticsMixin,
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

    def get_reporting_impressions_summary(self, days: int = 7) -> dict[str, object] | None:
        return collect_reporting_impressions(self.reporting_client, days)

    def get_traffic_source_analytics(self, start_date: str, end_date: str) -> dict:
        return collect_traffic_sources(self.analytics_service, self.channel_id, start_date, end_date)

    def get_traffic_source_detail(self, start_date: str, end_date: str, source_type: str) -> list[dict]:
        return collect_traffic_source_details(
            self.analytics_service, self.channel_id, start_date, end_date, source_type
        )

    def get_playlist_analytics(self, start_date: str, end_date: str) -> dict:
        return collect_playlist_analytics(self.analytics_service, self.channel_id, start_date, end_date)

    def get_subscribed_status_analytics(self, start_date: str, end_date: str) -> dict:
        return collect_subscribed_status_analytics(self.analytics_service, self.channel_id, start_date, end_date)

    def get_device_analytics(self, start_date: str, end_date: str) -> dict:
        return collect_device_analytics(self.analytics_service, self.channel_id, start_date, end_date)

    def get_country_analytics(self, start_date: str, end_date: str, max_countries: int = 20) -> dict:
        return collect_country_analytics(self.analytics_service, self.channel_id, start_date, end_date, max_countries)

    _parse_video_daily_rows = staticmethod(parse_video_daily_rows)

    def get_video_daily_analytics(
        self, start_date: str, end_date: str, video_ids: list[str] | None = None
    ) -> list[dict]:
        return collect_video_daily_analytics(
            self.analytics_service,
            self.channel_id,
            start_date,
            end_date,
            video_ids,
            parse_rows=self._parse_video_daily_rows,
        )

    def get_revenue_analytics(self, start_date: str, end_date: str) -> dict[str, object]:
        return collect_revenue_analytics(self.analytics_service, self.channel_id, start_date, end_date)

    def get_audience_retention(self, video_id: str, start_date: str, end_date: str) -> dict:
        return collect_audience_retention(self.analytics_service, self.channel_id, video_id, start_date, end_date)

    def get_retention_summary(self, start_date: str, end_date: str, top_n: int = 10) -> list[dict]:
        return collect_retention_summary(
            self.analytics_service,
            self.channel_id,
            start_date,
            end_date,
            top_n,
            get_video_details=self._get_video_details,
            get_retention=self.get_audience_retention,
        )
