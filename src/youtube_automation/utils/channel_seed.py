"""channel-new のベンチマーク seed fetch 操作."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from googleapiclient.errors import HttpError

from youtube_automation.utils.exceptions import ValidationError, YouTubeAPIError

CHANNELS_PART = "snippet,statistics,contentDetails"
PLAYLIST_ITEMS_PART = "snippet"
BENCHMARK_CHANNELS_KEY = "channels"
BENCHMARK_KEY = "benchmark"
CHANNEL_ID_PREFIX = "UC"
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]+$")
CHANNEL_ID_IN_HTML_RE = re.compile(rb'"(?:channelId|externalId)"\s*:\s*"(UC[A-Za-z0-9_-]+)"')
SLUG_INVALID_CHARS_RE = re.compile(r"[^a-z0-9]+")
HTML_FETCH_TIMEOUT_SEC = 15


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
    uploads_playlist_id = _extract_uploads_playlist_id(item)
    recent_titles = _fetch_recent_titles(youtube, uploads_playlist_id, recent)
    snippet = item["snippet"]
    stats = item["statistics"]
    channel_id = str(item["id"])
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

    parsed = urlparse(value)
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[0] == "channel" and path_parts[1].startswith(CHANNEL_ID_PREFIX):
        return path_parts[1]
    return None


def _handle_from_raw(raw: str) -> str | None:
    value = raw.strip()
    if value.startswith("@"):
        return value[1:]

    parsed = urlparse(value)
    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts and path_parts[0].startswith("@"):
        return path_parts[0][1:]
    if not parsed.scheme and not parsed.netloc and "/" not in value:
        return value
    return None


def _fetch_channel_by_id(youtube, channel_id: str) -> dict:
    try:
        response = youtube.channels().list(part=CHANNELS_PART, id=channel_id).execute()
    except HttpError as e:
        raise YouTubeAPIError.from_http_error(e, f"channels.list failed (id={channel_id})") from e
    return _single_channel_item(response, channel_id)


def _fetch_channel_by_handle(youtube, handle: str) -> dict:
    try:
        response = youtube.channels().list(part=CHANNELS_PART, forHandle=handle).execute()
    except HttpError as e:
        raise YouTubeAPIError.from_http_error(e, f"channels.list failed (handle=@{handle})") from e
    return _single_channel_item(response, f"@{handle}")


def _single_channel_item(response: dict, label: str) -> dict:
    items = response.get("items", [])
    if not items:
        raise ValidationError(f"YouTube channel not found: {label}")
    return items[0]


def _scrape_channel_id(raw: str) -> str:
    try:
        with urllib.request.urlopen(raw, timeout=HTML_FETCH_TIMEOUT_SEC) as response:
            html = response.read()
    except (urllib.error.URLError, TimeoutError) as e:
        raise YouTubeAPIError(f"YouTube channel page fetch failed ({raw}): {e}") from e
    match = CHANNEL_ID_IN_HTML_RE.search(html)
    if not match:
        raise ValidationError(f"Channel ID was not found in YouTube page: {raw}")
    return match.group(1).decode("ascii")


def _extract_uploads_playlist_id(item: dict) -> str:
    uploads = item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not uploads:
        raise ValidationError(f"Uploads playlist was not found for channel: {item['id']}")
    return str(uploads)


def _fetch_recent_titles(youtube, uploads_playlist_id: str, recent: int) -> list[str]:
    try:
        response = (
            youtube.playlistItems()
            .list(part=PLAYLIST_ITEMS_PART, playlistId=uploads_playlist_id, maxResults=recent)
            .execute()
        )
    except HttpError as e:
        raise YouTubeAPIError.from_http_error(e, f"playlistItems.list failed (playlist={uploads_playlist_id})") from e
    return [str(item["snippet"]["title"]) for item in response.get("items", [])]


def _slug_from_seed(seed: SeedChannel) -> str:
    if seed.handle:
        return seed.handle.removeprefix("@").lower()
    return SLUG_INVALID_CHARS_RE.sub("-", seed.name.lower()).strip("-")
