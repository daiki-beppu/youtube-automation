"""Instance-scoped Google API clients."""

from __future__ import annotations

from collections.abc import Callable

from googleapiclient.discovery import build

from youtube_automation.infrastructure.errors import ValidationError
from youtube_automation.infrastructure.retry import execute_with_retry


def create_authenticated_youtube_clients() -> "YouTubeClients":
    from youtube_automation.infrastructure.auth.youtube import YouTubeOAuthHandler

    return YouTubeClients(full_handler=YouTubeOAuthHandler())


def execute_youtube_request(request, context: str, *, on_attempt: Callable[[], None] | None = None):
    """Execute a prepared YouTube request behind the Google/I/O boundary."""
    return execute_with_retry(request, context, on_attempt=on_attempt)


def validate_youtube_response_items(response: object, operation: str) -> list[object]:
    if not isinstance(response, dict):
        raise ValidationError(f"{operation} response must be an object")
    items = response.get("items", [])
    if not isinstance(items, list):
        raise ValidationError(f"{operation} response items must be a list")
    return items


class YouTubeClients:
    """Resolve and cache API services within one execution scope."""

    def __init__(self, *, full_handler=None, readonly_handler=None):
        self._full_handler = full_handler
        self._readonly_handler = readonly_handler
        self._youtube = None
        self._youtube_readonly = None
        self._analytics = None
        self._reporting = None

    @property
    def _read_handler(self):
        return self._readonly_handler or self._full_handler

    @property
    def youtube(self):
        if self._youtube is None:
            self._youtube = self._full_handler.get_youtube_service()
        return self._youtube

    @property
    def youtube_readonly(self):
        if self._youtube_readonly is None:
            handler = self._read_handler
            self._youtube_readonly = handler.get_youtube_service()
        return self._youtube_readonly

    @property
    def analytics(self):
        if self._analytics is None:
            self._analytics = build("youtubeAnalytics", "v2", credentials=self._read_handler.authenticate())
        return self._analytics

    @property
    def reporting(self):
        if self._reporting is None:
            self._reporting = build("youtubereporting", "v1", credentials=self._read_handler.authenticate())
        return self._reporting

    def reset(self) -> None:
        self._youtube = None
        self._youtube_readonly = None
        self._analytics = None
        self._reporting = None
