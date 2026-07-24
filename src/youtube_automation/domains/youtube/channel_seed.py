"""channel-new のベンチマーク seed fetch 操作."""

from __future__ import annotations

import re
from dataclasses import dataclass

from youtube_automation.infrastructure.browser import RedirectRejectedError, fetch_html, parse_url
from youtube_automation.infrastructure.errors import ValidationError, YouTubeAPIError
from youtube_automation.infrastructure.google.upload import HttpError
from youtube_automation.infrastructure.google.youtube import execute_youtube_request, validate_youtube_response_items

CHANNELS_PART = "snippet,statistics,contentDetails"
PLAYLIST_ITEMS_PART = "snippet"
BENCHMARK_CHANNELS_KEY = "channels"
BENCHMARK_KEY = "benchmark"
CHANNEL_ID_PREFIX = "UC"
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]+$")
CHANNEL_ID_IN_HTML_RE = re.compile(rb'"(?:channelId|externalId)"\s*:\s*"(UC[A-Za-z0-9_-]+)"')
SLUG_INVALID_CHARS_RE = re.compile(r"[^a-z0-9]+")
HTML_FETCH_TIMEOUT_SEC = 15
ALLOWED_YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com"})


@dataclass(frozen=True)
class SeedChannel:
    channel_id: str
    handle: str
    name: str
    subscribers: int
    total_videos: int
    uploads_playlist_id: str
    recent_titles: tuple[str, ...]


def fetch_channel_seed(youtube, raw: str, *, recent: int) -> SeedChannel:
    item = _resolve_channel_item(youtube, raw)
    _validate_channel_item(item)
    uploads_playlist_id = _extract_uploads_playlist_id(item)
    recent_titles = _fetch_recent_titles(youtube, uploads_playlist_id, recent)
    snippet = item["snippet"]
    stats = item["statistics"]
    channel_id = item["id"]
    return SeedChannel(
        channel_id=channel_id,
        handle=str(snippet.get("customUrl", "")),
        name=str(snippet["title"]),
        subscribers=int(stats.get("subscriberCount", 0)),
        total_videos=int(stats.get("videoCount", 0)),
        uploads_playlist_id=uploads_playlist_id,
        recent_titles=tuple(recent_titles),
    )


def to_benchmark_entry(seed: SeedChannel, *, relationship: str) -> dict:
    return {
        "id": seed.channel_id,
        "slug": _slug_from_seed(seed),
        "name": seed.name,
        "relationship": relationship,
    }


def merge_benchmark_channel(analytics: dict, entry: dict) -> dict:
    benchmark = analytics[BENCHMARK_KEY]
    channels = benchmark[BENCHMARK_CHANNELS_KEY]
    if any(channel["id"] == entry["id"] for channel in channels):
        new_channels = list(channels)
    else:
        new_channels = [*channels, dict(entry)]
    return {
        **analytics,
        BENCHMARK_KEY: {
            **benchmark,
            BENCHMARK_CHANNELS_KEY: new_channels,
        },
    }


def _resolve_channel_item(youtube, raw: str) -> dict:
    channel_id = _channel_id_from_raw(raw)
    if channel_id:
        return _fetch_channel_by_id(youtube, channel_id)

    handle = _handle_from_raw(raw)
    if handle:
        return _fetch_channel_by_handle(youtube, handle)

    scraped_channel_id = _scrape_channel_id(raw)
    return _fetch_channel_by_id(youtube, scraped_channel_id)


def _channel_id_from_raw(raw: str) -> str | None:
    value = raw.strip()
    if CHANNEL_ID_RE.fullmatch(value):
        return value

    parsed = parse_url(value)
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[0] == "channel" and path_parts[1].startswith(CHANNEL_ID_PREFIX):
        return path_parts[1]
    return None


def _handle_from_raw(raw: str) -> str | None:
    value = raw.strip()
    if value.startswith("@"):
        return value[1:]

    parsed = parse_url(value)
    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts and path_parts[0].startswith("@"):
        return path_parts[0][1:]
    if not parsed.scheme and not parsed.netloc and "/" not in value:
        return value
    return None


def _fetch_channel_by_id(youtube, channel_id: str) -> dict:
    try:
        response = execute_youtube_request(
            youtube.channels().list(part=CHANNELS_PART, id=channel_id),
            "channels.list failed",
        )
    except HttpError as e:
        raise YouTubeAPIError.from_http_error(e, f"channels.list failed (id={channel_id})") from e
    return _single_channel_item(response, channel_id)


def _fetch_channel_by_handle(youtube, handle: str) -> dict:
    try:
        response = execute_youtube_request(
            youtube.channels().list(part=CHANNELS_PART, forHandle=handle),
            "channels.list failed",
        )
    except HttpError as e:
        raise YouTubeAPIError.from_http_error(e, f"channels.list failed (handle=@{handle})") from e
    return _single_channel_item(response, f"@{handle}")


def _single_channel_item(response: dict, label: str) -> dict:
    items = validate_youtube_response_items(response, f"YouTube channel response: {label}")
    if not items:
        raise ValidationError(f"YouTube channel not found: {label}")
    item = items[0]
    if not isinstance(item, dict):
        raise ValidationError(f"YouTube channel response item must be an object: {label}")
    return item


def _validate_channel_item(item: dict) -> None:
    if not isinstance(item.get("id"), str) or not item["id"]:
        raise ValidationError("YouTube channel response is missing id")
    snippet = item.get("snippet")
    if not isinstance(snippet, dict) or not isinstance(snippet.get("title"), str):
        raise ValidationError("YouTube channel response is missing snippet.title")
    statistics = item.get("statistics")
    if not isinstance(statistics, dict):
        raise ValidationError("YouTube channel response is missing statistics")
    content_details = item.get("contentDetails")
    related_playlists = content_details.get("relatedPlaylists") if isinstance(content_details, dict) else None
    if not isinstance(related_playlists, dict):
        raise ValidationError("YouTube channel response is missing contentDetails.relatedPlaylists")


def _scrape_channel_id(raw: str) -> str:
    parsed = parse_url(raw)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_YOUTUBE_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
    ):
        raise ValidationError("Channel seed URL must be an HTTPS youtube.com URL without credentials or a custom port")

    try:
        html = fetch_html(raw, timeout=HTML_FETCH_TIMEOUT_SEC)
    except (RedirectRejectedError, TimeoutError, OSError) as e:
        raise YouTubeAPIError(f"YouTube channel page fetch failed ({raw}): {e}") from e
    match = CHANNEL_ID_IN_HTML_RE.search(html)
    if not match:
        raise ValidationError(f"Channel ID was not found in YouTube page: {raw}")
    return match.group(1).decode("ascii")


def _extract_uploads_playlist_id(item: dict) -> str:
    content_details = item.get("contentDetails")
    related_playlists = content_details.get("relatedPlaylists") if isinstance(content_details, dict) else None
    uploads = related_playlists.get("uploads") if isinstance(related_playlists, dict) else None
    if not isinstance(uploads, str) or not uploads:
        channel_id = item.get("id", "<unknown>")
        raise ValidationError(f"Uploads playlist was not found for channel: {channel_id}")
    return uploads


def _fetch_recent_titles(youtube, uploads_playlist_id: str, recent: int) -> list[str]:
    try:
        response = execute_youtube_request(
            youtube.playlistItems().list(
                part=PLAYLIST_ITEMS_PART,
                playlistId=uploads_playlist_id,
                maxResults=recent,
            ),
            "playlistItems.list failed",
        )
    except HttpError as e:
        raise YouTubeAPIError.from_http_error(e, f"playlistItems.list failed (playlist={uploads_playlist_id})") from e
    items = validate_youtube_response_items(response, "playlistItems.list")
    titles = []
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError("playlistItems.list response item must be an object")
        snippet = item.get("snippet")
        if not isinstance(snippet, dict) or not isinstance(snippet.get("title"), str):
            raise ValidationError("playlistItems.list response item is missing snippet.title")
        titles.append(snippet["title"])
    return titles


def _slug_from_seed(seed: SeedChannel) -> str:
    if seed.handle:
        return seed.handle.removeprefix("@").lower()
    return SLUG_INVALID_CHARS_RE.sub("-", seed.name.lower()).strip("-")
