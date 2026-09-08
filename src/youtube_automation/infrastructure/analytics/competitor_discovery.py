"""競合探索の YouTube API 通信と検索キャッシュを所有する。

設定による除外と探索の実行順は application.analytics.competitor_discovery、
純粋なスコアリングとフィルタは competitor_scoring が所有する。
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from enum import Enum
from pathlib import Path

from youtube_automation.core.channel_context import channel_dir
from youtube_automation.infrastructure.analytics.competitor_scoring import (
    _RECENT_VIDEOS_PER_CHANNEL,
    CandidateChannel,
    VideoMetric,
)
from youtube_automation.infrastructure.retry import execute_with_retry

# channels.list バッチ単位（YouTube Data API 上限）
_CHANNELS_BATCH_SIZE = 50
_SEARCH_CACHE_TTL_SECONDS = 24 * 60 * 60
_SEARCH_CACHE_VERSION = 1
logger = logging.getLogger(__name__)


class SearchCacheMode(Enum):
    """search.list キャッシュの利用方針。"""

    USE = "use"
    REFRESH = "refresh"


def _search_cache_path() -> Path:
    return channel_dir() / ".cache" / "youtube-automation" / "discover-competitors-search.json"


def _cache_key(keyword: str, max_results: int) -> str:
    return json.dumps([keyword, max_results], ensure_ascii=False, separators=(",", ":"))


def _read_search_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("検索キャッシュを読み込めないため再検索します: %s", error)
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("version") != _SEARCH_CACHE_VERSION
        or not isinstance(payload.get("entries"), dict)
    ):
        logger.warning("検索キャッシュの形式が不正なため再検索します: %s", path)
        return {}
    return payload["entries"]


def _write_search_cache(path: Path, entries: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": _SEARCH_CACHE_VERSION, "entries": entries}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _cached_search_channels(
    youtube,
    keyword: str,
    max_results: int,
    cache_mode: SearchCacheMode,
) -> dict[str, set[str]]:
    path = _search_cache_path()
    entries = _read_search_cache(path)
    key = _cache_key(keyword, max_results)
    entry = entries.get(key)
    now = time.time()
    if cache_mode is SearchCacheMode.USE and isinstance(entry, dict):
        saved_at = entry.get("saved_at")
        channel_ids = entry.get("channel_ids")
        if (
            isinstance(saved_at, (int, float))
            and 0 <= now - saved_at < _SEARCH_CACHE_TTL_SECONDS
            and isinstance(channel_ids, list)
            and all(isinstance(channel_id, str) for channel_id in channel_ids)
        ):
            return {channel_id: {keyword} for channel_id in channel_ids}

    hits = _search_channels(youtube, keyword, max_results)
    entries[key] = {"saved_at": now, "channel_ids": list(hits)}
    _write_search_cache(path, entries)
    return hits


# ----------------------------------------------------------------------------
# YouTube API 呼び出し（HttpError は YouTubeAPIError に包む）
# ----------------------------------------------------------------------------


def _search_channels(youtube, keyword: str, max_results: int) -> dict[str, set[str]]:
    """search.list を実行し、ヒットした channel_id → {keyword} のマップを返す。

    骨格 `CandidateChannel` を作らない（後段で `_fetch_channel_details` が実体を組み立てる）。
    重複 channel_id は呼び出し側で union する。
    """
    request = youtube.search().list(
        part="snippet",
        q=keyword,
        type="channel",
        maxResults=max_results,
    )
    resp = execute_with_retry(request, f"search.list failed (q={keyword!r})")

    hits: dict[str, set[str]] = {}
    for item in resp.get("items", []):
        snippet = item.get("snippet", {})
        ch_id = snippet.get("channelId")
        if not ch_id:
            continue
        hits.setdefault(ch_id, set()).add(keyword)
    return hits


def _fetch_channel_details(
    youtube,
    channel_ids: list[str],
    keyword_map: dict[str, set[str]],
) -> tuple[list[CandidateChannel], dict[str, str]]:
    """channels.list でメタデータと uploads playlist を取得する。"""
    fetched: list[CandidateChannel] = []
    uploads_map: dict[str, str] = {}
    for i in range(0, len(channel_ids), _CHANNELS_BATCH_SIZE):
        batch = channel_ids[i : i + _CHANNELS_BATCH_SIZE]
        request = youtube.channels().list(part="snippet,statistics,contentDetails,topicDetails", id=",".join(batch))
        resp = execute_with_retry(request, "channels.list failed")

        for item in resp.get("items", []):
            ch_id = item["id"]
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})
            topic_details = item.get("topicDetails", {})
            uploads = content.get("relatedPlaylists", {}).get("uploads")
            if uploads:
                uploads_map[ch_id] = uploads
            fetched.append(
                CandidateChannel(
                    channel_id=ch_id,
                    handle=snippet.get("customUrl", ""),
                    name=snippet.get("title", ""),
                    subscribers=int(stats.get("subscriberCount", 0)),
                    total_videos=int(stats.get("videoCount", 0)),
                    matched_keywords=set(keyword_map.get(ch_id, set())),
                    recent_videos=[],
                    last_posted_at=None,
                    topic_categories=tuple(topic_details.get("topicCategories", [])),
                )
            )
    return fetched, uploads_map


def _fetch_recent_videos(youtube, uploads_playlist_id: str) -> list[VideoMetric]:
    """uploads playlist から直近動画を `_RECENT_VIDEOS_PER_CHANNEL` 本取得する。"""
    request = youtube.playlistItems().list(
        part="contentDetails",
        playlistId=uploads_playlist_id,
        maxResults=_RECENT_VIDEOS_PER_CHANNEL,
    )
    playlist_resp = execute_with_retry(request, f"playlistItems.list failed (playlist={uploads_playlist_id})")

    video_ids = [item["contentDetails"]["videoId"] for item in playlist_resp.get("items", [])]
    if not video_ids:
        return []

    request = youtube.videos().list(part="snippet,statistics", id=",".join(video_ids))
    videos_resp = execute_with_retry(request, "videos.list failed")

    metrics: list[VideoMetric] = []
    for item in videos_resp.get("items", []):
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        published_str = snippet.get("publishedAt", "")
        if not published_str:
            continue
        try:
            published = datetime.strptime(published_str[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        metrics.append(
            VideoMetric(
                views=int(stats.get("viewCount", 0)),
                likes=int(stats.get("likeCount", 0)),
                comments=int(stats.get("commentCount", 0)),
                published_at=published,
            )
        )
    return metrics
