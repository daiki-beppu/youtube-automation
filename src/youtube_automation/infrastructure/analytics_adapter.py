"""External boundary adapters for analytics clients."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from typing import Protocol

from googleapiclient.errors import HttpError
from httplib2 import HttpLib2Error

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.analytics.ports import AnalyticsResponse
from youtube_automation.infrastructure.retry import execute_with_retry


class _AnalyticsRequest(Protocol):
    @abstractmethod
    def execute(self) -> AnalyticsResponse: ...


class _AnalyticsReports(Protocol):
    @abstractmethod
    def query(self, **kwargs: object) -> _AnalyticsRequest: ...


class _AnalyticsService(Protocol):
    @abstractmethod
    def reports(self) -> _AnalyticsReports: ...


class _DataResource(Protocol):
    @abstractmethod
    def list(self, **kwargs: object) -> _AnalyticsRequest: ...


class _YouTubeService(Protocol):
    @abstractmethod
    def channels(self) -> _DataResource: ...
    @abstractmethod
    def playlistItems(self) -> _DataResource: ...
    @abstractmethod
    def playlists(self) -> _DataResource: ...
    @abstractmethod
    def videos(self) -> _DataResource: ...


class _RequestExecutor:
    """Share retry and per-attempt accounting policy across Google API adapters."""

    def __init__(self, *, retry_requests: bool, on_request: Callable[[str], None] | None) -> None:
        self._retry_requests = retry_requests
        self._on_request = on_request

    def _execute(self, request: _AnalyticsRequest, bucket: str, context: str) -> AnalyticsResponse:
        return execute_request(
            request,
            context,
            retry_requests=self._retry_requests,
            on_attempt=lambda: self._record_request(bucket),
        )

    def _record_request(self, bucket: str) -> None:
        if self._on_request is not None:
            self._on_request(bucket)


class AnalyticsAdapter(_RequestExecutor):
    """Adapt the Google Analytics reporting client to the analytics port."""

    def __init__(
        self,
        client: _AnalyticsService,
        *,
        retry_requests: bool,
        on_request: Callable[[str], None] | None = None,
    ) -> None:
        self._client = client
        super().__init__(retry_requests=retry_requests, on_request=on_request)

    def query(self, **kwargs: object) -> AnalyticsResponse:
        request = self._client.reports().query(**kwargs)
        return self._execute(request, "reports.query", "YouTube Analytics API request failed")


def execute_request(
    request: _AnalyticsRequest,
    context: str,
    *,
    retry_requests: bool,
    on_attempt: Callable[[], None] | None = None,
) -> AnalyticsResponse:
    if retry_requests:
        return execute_with_retry(request, context, on_attempt=on_attempt)
    try:
        return request.execute()
    except HttpError as error:
        raise YouTubeAPIError.from_http_error(error, context) from error
    except (HttpLib2Error, OSError) as error:
        raise YouTubeAPIError(f"{context}: {error}") from error
    finally:
        if on_attempt is not None:
            on_attempt()


class YouTubeDataAdapter(_RequestExecutor):
    """Expose named Data API operations without leaking request chains."""

    def __init__(
        self,
        service: _YouTubeService,
        *,
        retry_requests: bool,
        on_request: Callable[[str], None] | None = None,
    ) -> None:
        self._service = service
        super().__init__(retry_requests=retry_requests, on_request=on_request)

    def resolve_channel(self) -> AnalyticsResponse:
        response = self._execute(
            self._service.channels().list(part="id,snippet,statistics", mine=True),
            "channels.list",
            "YouTube channel lookup",
        )
        items = response.get("items", [])
        return items[0] if items else {}

    def list_uploads(self, channel_id: str) -> AnalyticsResponse:
        return self._execute(
            self._service.channels().list(part="contentDetails", id=channel_id),
            "channels.list",
            "YouTube Data API request failed",
        )

    def list_playlist_items(self, playlist_id: str, page_token: str | None) -> AnalyticsResponse:
        return self._execute(
            self._service.playlistItems().list(
                part="snippet,contentDetails", playlistId=playlist_id, maxResults=50, pageToken=page_token
            ),
            "playlistItems.list",
            "YouTube Analytics API request failed",
        )

    def list_playlists(self, channel_id: str) -> AnalyticsResponse:
        return self._execute(
            self._service.playlists().list(part="snippet", channelId=channel_id, maxResults=50),
            "playlists.list",
            "YouTube Data API request failed",
        )

    def list_playlist_items_for_display(self, playlist_id: str, *, max_results: int) -> AnalyticsResponse:
        return self._execute(
            self._service.playlistItems().list(part="snippet", playlistId=playlist_id, maxResults=max_results),
            "playlistItems.list",
            "YouTube Data API request failed",
        )

    def list_videos(self, video_ids: str, *, part: str) -> AnalyticsResponse:
        return self._execute(
            self._service.videos().list(part=part, id=video_ids),
            "videos.list",
            "YouTube Analytics API request failed",
        )
