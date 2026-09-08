"""競合探索の設定による除外と、検索・評価の実行順を管理する。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from youtube_automation.configuration import load_config
from youtube_automation.infrastructure.analytics import competitor_discovery as discovery_io
from youtube_automation.infrastructure.analytics.competitor_scoring import (
    CandidateChannel,
    DiscoveryParams,
    ScoredCandidate,
    _apply_filters,
    _score_candidate,
)


def _discovered_channel_ids() -> set[str]:
    return {
        channel_id
        for channel in load_config().analytics.benchmark.channels
        if isinstance(channel, dict) and isinstance((channel_id := channel.get("id")), str) and channel_id
    }


def discover_competitors(
    youtube,
    params: DiscoveryParams,
    cache_mode: discovery_io.SearchCacheMode = discovery_io.SearchCacheMode.USE,
) -> list[ScoredCandidate]:
    """競合チャンネル候補を発掘し、複合スコア降順で返す。

    パイプライン:
      1. TTL キャッシュまたは search.list × keywords → channel_id → matched_keywords map（直接 union）
      2. benchmark.channels の検出済み channel ID を除外
      3. channels.list → メタデータ + uploads playlist
      4. _apply_filters（subs / total_videos）
      5. _fetch_recent_videos → recent_videos + last_posted_at
      6. _apply_filters（posted_within_days）
      7. _score_candidate + sort + top N
    """
    keyword_map: dict[str, set[str]] = defaultdict(set)
    for keyword in params.keywords:
        for ch_id, kws in discovery_io._cached_search_channels(
            youtube, keyword, params.per_keyword_results, cache_mode
        ).items():
            keyword_map[ch_id] |= kws

    for channel_id in _discovered_channel_ids():
        keyword_map.pop(channel_id, None)

    if not keyword_map:
        return []

    channel_ids = list(keyword_map.keys())

    fetched, uploads_map = discovery_io._fetch_channel_details(youtube, channel_ids, keyword_map)
    pre_filtered = _apply_filters(fetched, params)

    enriched: list[CandidateChannel] = []
    for ch in pre_filtered:
        uploads = uploads_map.get(ch.channel_id)
        if not uploads:
            continue
        recent = discovery_io._fetch_recent_videos(youtube, uploads)
        if not recent:
            continue
        last_posted = max((v.published_at for v in recent), default=None)
        enriched.append(replace(ch, recent_videos=recent, last_posted_at=last_posted))

    posted_filtered = _apply_filters(enriched, params)

    scored = [_score_candidate(ch, params) for ch in posted_filtered]
    scored.sort(key=lambda s: s.score.total, reverse=True)

    return scored[: params.top]
