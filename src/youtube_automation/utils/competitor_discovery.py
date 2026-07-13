"""yt-discover-competitors のパイプライン orchestration（Issue #114）。

YouTube Data API I/O と公開関数 `discover_competitors` を提供する。
ドメイン型・純粋スコアリング・フィルタは `competitor_scoring.py` を参照。

設計方針:
- 境界（CLI）で `DiscoveryParams` に正規化された値だけをこのモジュールが受け取る
- API 呼び出しと純粋関数を別モジュールに分離する
- `googleapiclient.errors.HttpError` は `YouTubeAPIError` で包む
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime

from youtube_automation.utils.competitor_scoring import (
    _RECENT_VIDEOS_PER_CHANNEL,
    CandidateChannel,
    DiscoveryParams,
    ScoredCandidate,
    VideoMetric,
    _apply_filters,
    _score_candidate,
)
from youtube_automation.utils.exceptions import YouTubeAPIError
from youtube_automation.utils.retry import execute_with_retry

# channels.list バッチ単位（YouTube Data API 上限）
_CHANNELS_BATCH_SIZE = 50


# ----------------------------------------------------------------------------
# YouTube API 呼び出し（HttpError は YouTubeAPIError に包む）
# ----------------------------------------------------------------------------


def _search_channels(youtube, keyword: str, max_results: int) -> dict[str, set[str]]:
    """search.list を実行し、ヒットした channel_id → {keyword} のマップを返す。

    骨格 `CandidateChannel` を作らない（後段で `_fetch_channel_details` が実体を組み立てる）。
    重複 channel_id は呼び出し側で union する。
    """
    try:
        request = youtube.search().list(
            part="snippet",
            q=keyword,
            type="channel",
            maxResults=max_results,
        )
        resp = execute_with_retry(request, f"search.list failed (q={keyword!r})")
    except YouTubeAPIError:
        raise

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
        try:
            request = youtube.channels().list(part="snippet,statistics,contentDetails,topicDetails", id=",".join(batch))
            resp = execute_with_retry(request, "channels.list failed")
        except YouTubeAPIError:
            raise

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
    try:
        request = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist_id,
            maxResults=_RECENT_VIDEOS_PER_CHANNEL,
        )
        playlist_resp = execute_with_retry(request, f"playlistItems.list failed (playlist={uploads_playlist_id})")
    except YouTubeAPIError:
        raise

    video_ids = [item["contentDetails"]["videoId"] for item in playlist_resp.get("items", [])]
    if not video_ids:
        return []

    try:
        request = youtube.videos().list(part="snippet,statistics", id=",".join(video_ids))
        videos_resp = execute_with_retry(request, "videos.list failed")
    except YouTubeAPIError:
        raise

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


# ----------------------------------------------------------------------------
# パブリック API
# ----------------------------------------------------------------------------


def discover_competitors(youtube, params: DiscoveryParams) -> list[ScoredCandidate]:
    """競合チャンネル候補を発掘し、複合スコア降順で返す。

    パイプライン:
      1. search.list × keywords → channel_id → matched_keywords map（直接 union）
      2. channels.list → メタデータ + uploads playlist
      3. _apply_filters（subs / total_videos）
      4. _fetch_recent_videos → recent_videos + last_posted_at
      5. _apply_filters（posted_within_days）
      6. _score_candidate + sort + top N
    """
    keyword_map: dict[str, set[str]] = defaultdict(set)
    for keyword in params.keywords:
        for ch_id, kws in _search_channels(youtube, keyword, params.per_keyword_results).items():
            keyword_map[ch_id] |= kws

    if not keyword_map:
        return []

    channel_ids = list(keyword_map.keys())

    fetched, uploads_map = _fetch_channel_details(youtube, channel_ids, keyword_map)
    pre_filtered = _apply_filters(fetched, params)

    enriched: list[CandidateChannel] = []
    for ch in pre_filtered:
        uploads = uploads_map.get(ch.channel_id)
        if not uploads:
            continue
        recent = _fetch_recent_videos(youtube, uploads)
        last_posted = max((v.published_at for v in recent), default=None)
        enriched.append(replace(ch, recent_videos=recent, last_posted_at=last_posted))

    posted_filtered = _apply_filters(enriched, params)

    scored = [_score_candidate(ch, params) for ch in posted_filtered]
    scored.sort(key=lambda s: s.score.total, reverse=True)

    return scored[: params.top]
