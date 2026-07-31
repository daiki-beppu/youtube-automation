"""yt-discover-competitors のドメイン型と純粋スコアリング層（Issue #114）。

YouTube API I/O は持たず、`DiscoveryParams` 等の dataclass と
4 軸スコアリング・フィルタ・候補理由整形などの純粋関数のみを置く。
パイプライン orchestration（`discover_competitors`）と API I/O は
`competitor_discovery.py` を参照。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# スコア重み（plan §4.3）。重み総和 = 1.0 → 全成分 1.0 のとき total = 1.0 になる
_WEIGHT_KEYWORD = 0.30
_WEIGHT_ENGAGEMENT = 0.25
_WEIGHT_POSTING = 0.25
_WEIGHT_PROXIMITY = 0.20

# ER（(likes+comments)/views）が 10% で 1.0 に飽和するように正規化する
_ENGAGEMENT_SATURATION = 0.10

# 直近動画の取得本数（plan §3 「最大 5 本」）。`_compute_posting_cadence` の
# 期間内本数正規化と、API 取得本数 (`_fetch_recent_videos`) の双方で共有する。
_RECENT_VIDEOS_PER_CHANNEL = 5

# 1 ヶ月の概算日数（更新頻度の月次換算）
_DAYS_PER_MONTH = 30.0

# 候補理由のトップ要因数
_REASON_TOP_FACTORS = 2

_FACTOR_PHRASES: dict[str, str] = {
    "keyword_match": "キーワード一致率高",
    "engagement": "エンゲージメント率高",
    "posting_cadence": "更新頻度高",
    "subscriber_proximity": "近い登録者帯",
}

# 音楽トピック判定用 Wikipedia URL（freebase 後継の topicCategories と同形式）。
# `channels.list part=topicDetails` の `topicCategories` を prefix マッチで判定する。
# Issue #120: 非音楽チャンネルの誤検知（例: "Lo-Fi House" インテリア / DIY 系）を構造的に抑制する。
_MUSIC_TOPIC_URLS: frozenset[str] = frozenset(
    {
        "https://en.wikipedia.org/wiki/Music",
        "https://en.wikipedia.org/wiki/Electronic_music",
        "https://en.wikipedia.org/wiki/Hip_hop_music",
        "https://en.wikipedia.org/wiki/Pop_music",
        "https://en.wikipedia.org/wiki/Rock_music",
        "https://en.wikipedia.org/wiki/Classical_music",
        "https://en.wikipedia.org/wiki/Independent_music",
        "https://en.wikipedia.org/wiki/Jazz",
        "https://en.wikipedia.org/wiki/Country_music",
        "https://en.wikipedia.org/wiki/Soul_music",
        "https://en.wikipedia.org/wiki/Reggae",
    }
)


# ----------------------------------------------------------------------------
# Dataclasses
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscoveryParams:
    """CLI 境界で解決済みの探索パラメータ（不変）。"""

    keywords: tuple[str, ...]
    min_subscribers: int
    max_subscribers: int
    posted_within_days: int
    top: int
    per_keyword_results: int
    require_music_topic: bool = True


@dataclass
class VideoMetric:
    """直近動画 1 本の集計指標。"""

    views: int
    likes: int
    comments: int
    published_at: date


@dataclass
class CandidateChannel:
    """発掘候補チャンネル。recent_videos / last_posted_at は段階的に埋まる。"""

    channel_id: str
    handle: str
    name: str
    subscribers: int
    total_videos: int
    matched_keywords: set[str]
    recent_videos: list[VideoMetric]
    last_posted_at: date | None
    topic_categories: tuple[str, ...] = ()


@dataclass
class ScoreBreakdown:
    """スコア内訳。total は重み付き合算（0..1）。"""

    keyword_match: float
    engagement: float
    posting_cadence: float
    subscriber_proximity: float
    total: float


@dataclass
class ScoredCandidate:
    """ランキング出力単位。"""

    channel: CandidateChannel
    monthly_uploads: float
    avg_views: int
    score: ScoreBreakdown
    reason: str


# ----------------------------------------------------------------------------
# 純粋関数: フィルタ・スコアリング
# ----------------------------------------------------------------------------


def _is_music_topic_match(topic_categories: tuple[str, ...]) -> bool:
    """`topic_categories` の URL が `_MUSIC_TOPIC_URLS` のいずれかを prefix に持つか判定する。

    空入力は False を返す（fail-open は呼び出し側 `_apply_filters` の責務）。
    """
    return any(topic.startswith(prefix) for topic in topic_categories for prefix in _MUSIC_TOPIC_URLS)


def _apply_filters(channels: list[CandidateChannel], params: DiscoveryParams) -> list[CandidateChannel]:
    """登録者レンジ・動画本数・最終投稿日・音楽トピックでフィルタする（入力非破壊）。

    `last_posted_at is None` のチャンネルは投稿日フィルタを保留する
    （recent_videos 取得前のため。後段で再フィルタする）。

    `require_music_topic=True` のときのみ topic 判定を作用させ、
    `topic_categories` が空のチャンネルは fail-open で通す（判定不能 → 除外しない）。
    """
    today = date.today()
    result: list[CandidateChannel] = []
    for ch in channels:
        if ch.subscribers < params.min_subscribers or ch.subscribers > params.max_subscribers:
            continue
        if ch.total_videos == 0:
            continue
        if ch.last_posted_at is not None:
            days_since = (today - ch.last_posted_at).days
            if days_since > params.posted_within_days:
                continue
        if params.require_music_topic and ch.topic_categories and not _is_music_topic_match(ch.topic_categories):
            continue
        result.append(ch)
    return result


def _compute_keyword_match(channel: CandidateChannel, keywords: tuple[str, ...]) -> float:
    """`matched_keywords ∩ keywords` の比率（0..1）。"""
    if not keywords:
        return 0.0
    keywords_set = set(keywords)
    matched = channel.matched_keywords & keywords_set
    return len(matched) / len(keywords_set)


def _compute_engagement(videos: list[VideoMetric]) -> float:
    """直近動画の平均エンゲージメント率（0..1 にクランプ）。"""
    if not videos:
        return 0.0
    rates: list[float] = []
    for v in videos:
        # views=0 の動画はゼロ除算回避のため ER=0 として平均に寄与させる
        rates.append((v.likes + v.comments) / v.views if v.views > 0 else 0.0)
    avg_er = sum(rates) / len(rates)
    return min(avg_er / _ENGAGEMENT_SATURATION, 1.0)


def _compute_posting_cadence(videos: list[VideoMetric], posted_within_days: int) -> float:
    """更新頻度スコア（直近度 + 期間内本数の平均、0..1）。"""
    if not videos or posted_within_days <= 0:
        return 0.0
    today = date.today()
    newest = max(v.published_at for v in videos)
    days_since = max(0, (today - newest).days)
    recency = max(0.0, 1.0 - days_since / posted_within_days)

    within_window = sum(1 for v in videos if (today - v.published_at).days <= posted_within_days)
    frequency = min(within_window / _RECENT_VIDEOS_PER_CHANNEL, 1.0)

    return (recency + frequency) / 2.0


def _compute_subscriber_proximity(*, subscribers: int, min_: int, max_: int) -> float:
    """登録者帯近さ（中央 = 1.0、端 = 0、0..1）。

    `min_ == max_`（半径ゼロ範囲）はフィルタ通過済みを前提に full match (1.0) として扱う。
    （`_build_params` は `max == min` を許容するため、退化エッジを最低スコア扱いしない）
    """
    if max_ == min_:
        return 1.0
    center = (min_ + max_) / 2.0
    half_range = (max_ - min_) / 2.0
    distance = abs(subscribers - center)
    return max(0.0, 1.0 - distance / half_range)


def _combine_score(
    *,
    keyword_match: float,
    engagement: float,
    posting_cadence: float,
    subscriber_proximity: float,
) -> ScoreBreakdown:
    """4 軸スコアを重み付き合算する。重み総和 1.0 → 全成分 1.0 で total=1.0。"""
    total = (
        _WEIGHT_KEYWORD * keyword_match
        + _WEIGHT_ENGAGEMENT * engagement
        + _WEIGHT_POSTING * posting_cadence
        + _WEIGHT_PROXIMITY * subscriber_proximity
    )
    return ScoreBreakdown(
        keyword_match=keyword_match,
        engagement=engagement,
        posting_cadence=posting_cadence,
        subscriber_proximity=subscriber_proximity,
        total=total,
    )


def _format_reason(breakdown: ScoreBreakdown) -> str:
    """スコア上位 2 要因をフレーズ化する。"""
    factors = [
        ("keyword_match", breakdown.keyword_match),
        ("engagement", breakdown.engagement),
        ("posting_cadence", breakdown.posting_cadence),
        ("subscriber_proximity", breakdown.subscriber_proximity),
    ]
    factors.sort(key=lambda x: x[1], reverse=True)
    top = factors[:_REASON_TOP_FACTORS]
    return "、".join(_FACTOR_PHRASES[name] for name, _ in top)


# ----------------------------------------------------------------------------
# 月次投稿数・平均再生数（純粋関数、レポート列用）
# ----------------------------------------------------------------------------


def _compute_monthly_uploads(videos: list[VideoMetric]) -> float:
    """直近動画の投稿スパンから月次投稿数を推定する。"""
    if len(videos) < 2:
        return float(len(videos))
    dates = sorted(v.published_at for v in videos)
    span_days = max((dates[-1] - dates[0]).days, 1)
    months = span_days / _DAYS_PER_MONTH
    return len(videos) / months if months > 0 else float(len(videos))


def _compute_avg_views(videos: list[VideoMetric]) -> int:
    if not videos:
        return 0
    return round(sum(v.views for v in videos) / len(videos))


def _score_candidate(channel: CandidateChannel, params: DiscoveryParams) -> ScoredCandidate:
    """単一候補をスコア化する（純粋関数の合成）。"""
    keyword_match = _compute_keyword_match(channel, params.keywords)
    engagement = _compute_engagement(channel.recent_videos)
    posting_cadence = _compute_posting_cadence(channel.recent_videos, params.posted_within_days)
    subscriber_proximity = _compute_subscriber_proximity(
        subscribers=channel.subscribers,
        min_=params.min_subscribers,
        max_=params.max_subscribers,
    )
    breakdown = _combine_score(
        keyword_match=keyword_match,
        engagement=engagement,
        posting_cadence=posting_cadence,
        subscriber_proximity=subscriber_proximity,
    )
    return ScoredCandidate(
        channel=channel,
        monthly_uploads=_compute_monthly_uploads(channel.recent_videos),
        avg_views=_compute_avg_views(channel.recent_videos),
        score=breakdown,
        reason=_format_reason(breakdown),
    )
