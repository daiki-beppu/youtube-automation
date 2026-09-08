"""Ports used by analytics application services."""

from abc import abstractmethod
from typing import Protocol

AnalyticsResponse = dict[str, object]


class AnalyticsClient(Protocol):
    @abstractmethod
    def query(self, **kwargs: object) -> AnalyticsResponse: ...


class YouTubeClient(Protocol):
    @abstractmethod
    def resolve_channel(self) -> AnalyticsResponse: ...

    @abstractmethod
    def list_uploads(self, channel_id: str) -> AnalyticsResponse: ...

    @abstractmethod
    def list_playlist_items(self, playlist_id: str, page_token: str | None) -> AnalyticsResponse: ...

    @abstractmethod
    def list_playlists(self, channel_id: str) -> AnalyticsResponse: ...

    @abstractmethod
    def list_playlist_items_for_display(self, playlist_id: str, *, max_results: int) -> AnalyticsResponse: ...

    @abstractmethod
    def list_videos(self, video_ids: str, *, part: str) -> AnalyticsResponse: ...


class ReportingClient(Protocol):
    @abstractmethod
    def collect_impressions_summary(self, *, days: int) -> AnalyticsResponse: ...


class AnalyticsBase(Protocol):
    youtube_service: YouTubeClient
    analytics_service: AnalyticsClient
    channel_id: str | None

    @abstractmethod
    def initialize(self) -> None: ...

    @abstractmethod
    def _get_video_details(self, video_ids: list[str]) -> AnalyticsResponse: ...

    @abstractmethod
    def get_all_channel_videos(self) -> list[AnalyticsResponse]: ...

    @abstractmethod
    def get_scheduled_video_count(self) -> int: ...

    @abstractmethod
    def get_video_analytics_by_id(self, video_id: str, start_date: str, end_date: str) -> AnalyticsResponse: ...

    @abstractmethod
    def get_video_analytics(self, start_date: str, end_date: str) -> list[AnalyticsResponse]: ...

    @abstractmethod
    def get_recent_videos(self, days: int) -> list[AnalyticsResponse]: ...
