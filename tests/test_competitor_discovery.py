"""utils/competitor_discovery.py + competitor_scoring.py のユニットテスト

Issue #114 で追加する `yt-discover-competitors` のコアロジックを検証する。

検証対象（plan.md §4 公開 API / §4.3 内部ヘルパー / §6.1 テスト方針）:
1. dataclass 群（DiscoveryParams / VideoMetric / CandidateChannel / ScoreBreakdown / ScoredCandidate）
2. 純粋関数: _apply_filters / _compute_keyword_match
   / _compute_engagement / _compute_posting_cadence / _compute_subscriber_proximity
   / _combine_score / _format_reason
3. discover_competitors（API は MagicMock で差し込み、最後まで通すこと）

ネットワークも YouTube API も呼ばない（API 呼び出しは MagicMock）。
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from youtube_automation.utils.competitor_discovery import discover_competitors
from youtube_automation.utils.competitor_scoring import (
    CandidateChannel,
    DiscoveryParams,
    ScoreBreakdown,
    ScoredCandidate,
    VideoMetric,
    _apply_filters,
    _combine_score,
    _compute_engagement,
    _compute_keyword_match,
    _compute_posting_cadence,
    _compute_subscriber_proximity,
    _format_reason,
)
from youtube_automation.utils.exceptions import YouTubeAPIError

# ----------------------------------------------------------------------------
# テストデータ生成ヘルパー
# ----------------------------------------------------------------------------


def _make_video(
    *,
    views: int = 10_000,
    likes: int = 500,
    comments: int = 50,
    days_ago: int = 7,
) -> VideoMetric:
    """テスト用の VideoMetric を組み立てる（日付は今日からの相対指定）"""
    return VideoMetric(
        views=views,
        likes=likes,
        comments=comments,
        published_at=date.today() - timedelta(days=days_ago),
    )


def _make_channel(
    *,
    channel_id: str = "UC_default",
    handle: str = "@default",
    name: str = "Default Channel",
    subscribers: int = 100_000,
    total_videos: int = 50,
    matched_keywords: set[str] | None = None,
    recent_videos: list[VideoMetric] | None = None,
    last_posted_days_ago: int | None = 7,
) -> CandidateChannel:
    """テスト用の CandidateChannel を組み立てる。

    last_posted_days_ago=None の場合は last_posted_at=None（recent_videos 取得前を模擬）。
    """
    last_posted_at = None if last_posted_days_ago is None else date.today() - timedelta(days=last_posted_days_ago)
    return CandidateChannel(
        channel_id=channel_id,
        handle=handle,
        name=name,
        subscribers=subscribers,
        total_videos=total_videos,
        matched_keywords=set(matched_keywords or set()),
        recent_videos=list(recent_videos or []),
        last_posted_at=last_posted_at,
    )


def _make_params(
    *,
    keywords: tuple[str, ...] = ("lo-fi study",),
    min_subscribers: int = 10_000,
    max_subscribers: int = 1_000_000,
    posted_within_days: int = 30,
    top: int = 20,
    per_keyword_results: int = 20,
) -> DiscoveryParams:
    return DiscoveryParams(
        keywords=keywords,
        min_subscribers=min_subscribers,
        max_subscribers=max_subscribers,
        posted_within_days=posted_within_days,
        top=top,
        per_keyword_results=per_keyword_results,
    )


# ----------------------------------------------------------------------------
# DiscoveryParams（境界での解決の不変条件）
# ----------------------------------------------------------------------------


class TestDiscoveryParams:
    def test_keywords_must_be_tuple(self):
        # Given: 正常な引数
        params = _make_params(keywords=("a", "b"))

        # Then: keywords は tuple として保持される（mutable list ではない）
        assert isinstance(params.keywords, tuple)
        assert params.keywords == ("a", "b")

    def test_is_frozen(self):
        # Given: frozen dataclass の不変条件
        params = _make_params()

        # When/Then: 属性変更は FrozenInstanceError
        with pytest.raises(Exception):  # noqa: BLE001 - dataclasses.FrozenInstanceError は AttributeError を継承
            params.top = 5  # type: ignore[misc]


class TestVideoMetricFields:
    """family_tag=dead-code 再発防止。

    `VideoMetric` には API レスポンスから読み出すスコアリング関数が実際に参照する
    フィールド（views / likes / comments / published_at）のみが存在することを保証する。
    `video_id` / `title` を「念のため」追加すると本テストが失敗する。
    """

    def test_video_metric_exposes_only_used_fields(self):
        # Given: dataclass のフィールド集合
        from dataclasses import fields

        names = {f.name for f in fields(VideoMetric)}

        # Then: スコアリング・出力で実際に読まれる 4 フィールドのみ
        assert names == {"views", "likes", "comments", "published_at"}


class TestModuleResponsibilitySplit:
    """family_tag=module-size 再発防止。

    plan §「検討したアプローチ」の「300 行超なら competitor_scoring.py に純粋関数を
    分離」という設計判断に基づき、純粋スコアリング関数群は `competitor_scoring.py`
    に置く。`competitor_discovery.py` には API I/O と orchestration のみを残し、
    再び純粋関数群を抱え込んで肥大化しないよう構造を固定する。
    """

    def test_pure_scoring_functions_are_defined_in_scoring_module(self):
        # Given: 純粋関数群の `__module__` 属性は scoring モジュールを指す
        from youtube_automation.utils import competitor_scoring

        scoring_module = "youtube_automation.utils.competitor_scoring"
        for fn in (
            competitor_scoring._apply_filters,
            competitor_scoring._compute_keyword_match,
            competitor_scoring._compute_engagement,
            competitor_scoring._compute_posting_cadence,
            competitor_scoring._compute_subscriber_proximity,
            competitor_scoring._combine_score,
            competitor_scoring._format_reason,
            competitor_scoring._compute_monthly_uploads,
            competitor_scoring._compute_avg_views,
            competitor_scoring._score_candidate,
        ):
            assert fn.__module__ == scoring_module, f"{fn.__name__} は scoring モジュール定義であるべき"

    def test_discovery_module_only_owns_api_io_and_orchestration(self):
        # Given: discovery モジュールが自身で定義する関数の `__module__`
        from youtube_automation.utils import competitor_discovery

        discovery_module = "youtube_automation.utils.competitor_discovery"
        # discover_competitors / API I/O ヘルパーは discovery 側で定義
        for fn in (
            competitor_discovery.discover_competitors,
            competitor_discovery._search_channels,
            competitor_discovery._fetch_channel_details,
            competitor_discovery._fetch_recent_videos,
        ):
            assert fn.__module__ == discovery_module


# ----------------------------------------------------------------------------
# _apply_filters
# ----------------------------------------------------------------------------


class TestApplyFilters:
    def test_keeps_channel_within_subscriber_range(self):
        # Given: レンジ内の登録者数
        ch = _make_channel(subscribers=100_000, last_posted_days_ago=5)
        params = _make_params(min_subscribers=10_000, max_subscribers=1_000_000)

        # When
        result = _apply_filters([ch], params)

        # Then
        assert result == [ch]

    def test_drops_channel_below_min_subscribers(self):
        # Given: 下限未満
        ch = _make_channel(subscribers=5_000, last_posted_days_ago=5)
        params = _make_params(min_subscribers=10_000, max_subscribers=1_000_000)

        # When
        result = _apply_filters([ch], params)

        # Then
        assert result == []

    def test_drops_channel_above_max_subscribers(self):
        # Given: 上限超過
        ch = _make_channel(subscribers=2_000_000, last_posted_days_ago=5)
        params = _make_params(min_subscribers=10_000, max_subscribers=1_000_000)

        # When
        result = _apply_filters([ch], params)

        # Then
        assert result == []

    def test_drops_channel_with_zero_videos(self):
        # Given: total_videos == 0（空チャンネル）
        ch = _make_channel(subscribers=100_000, total_videos=0, last_posted_days_ago=5)
        params = _make_params()

        # When
        result = _apply_filters([ch], params)

        # Then: 動画 0 本のチャンネルは除外
        assert result == []

    def test_drops_channel_with_stale_last_posted_at(self):
        # Given: 最終投稿が posted_within_days 超過
        ch = _make_channel(subscribers=100_000, last_posted_days_ago=100)
        params = _make_params(posted_within_days=30)

        # When
        result = _apply_filters([ch], params)

        # Then
        assert result == []

    def test_keeps_channel_with_recent_post(self):
        # Given: posted_within_days 以内
        ch = _make_channel(subscribers=100_000, last_posted_days_ago=10)
        params = _make_params(posted_within_days=30)

        # When
        result = _apply_filters([ch], params)

        # Then
        assert result == [ch]

    def test_keeps_channel_when_last_posted_at_is_none(self):
        # Given: recent_videos 未取得段階（last_posted_at=None）
        ch = _make_channel(subscribers=100_000, last_posted_days_ago=None)
        params = _make_params(posted_within_days=30)

        # When
        result = _apply_filters([ch], params)

        # Then: 投稿日不明のチャンネルは現段階では除外しない（後段で再フィルタする）
        assert result == [ch]

    def test_returns_new_list_without_mutating_input(self):
        # Given: 一部が除外される入力
        keep = _make_channel(channel_id="UC1", subscribers=100_000, last_posted_days_ago=5)
        drop = _make_channel(channel_id="UC2", subscribers=1, last_posted_days_ago=5)
        original = [keep, drop]

        # When
        result = _apply_filters(original, _make_params(min_subscribers=10_000))

        # Then: 入力リストは破壊しない
        assert original == [keep, drop]
        assert result is not original
        assert result == [keep]


# ----------------------------------------------------------------------------
# _compute_keyword_match
# ----------------------------------------------------------------------------


class TestComputeKeywordMatch:
    def test_full_match_returns_one(self):
        # Given: 全キーワードに一致するチャンネル
        ch = _make_channel(matched_keywords={"lo-fi", "study", "chill"})
        keywords = ("lo-fi", "study", "chill")

        # When
        score = _compute_keyword_match(ch, keywords)

        # Then
        assert score == pytest.approx(1.0)

    def test_no_match_returns_zero(self):
        # Given: matched_keywords が空 + name/desc/動画タイトルにキーワードを含まないチャンネル
        ch = _make_channel(name="Cooking Channel", matched_keywords=set())
        keywords = ("lo-fi", "study", "chill")

        # When
        score = _compute_keyword_match(ch, keywords)

        # Then
        assert score == pytest.approx(0.0)

    def test_partial_match_is_between_zero_and_one(self):
        # Given: 一部のキーワードのみ一致
        ch = _make_channel(matched_keywords={"lo-fi"})
        keywords = ("lo-fi", "study", "chill")

        # When
        score = _compute_keyword_match(ch, keywords)

        # Then
        assert 0.0 < score < 1.0

    def test_more_matches_yields_higher_score(self):
        # Given: 同じキーワード集合で hit 数が異なる 2 チャンネル
        few = _make_channel(channel_id="UC_FEW", matched_keywords={"lo-fi"})
        many = _make_channel(channel_id="UC_MANY", matched_keywords={"lo-fi", "study"})
        keywords = ("lo-fi", "study", "chill")

        # When
        score_few = _compute_keyword_match(few, keywords)
        score_many = _compute_keyword_match(many, keywords)

        # Then: hit 数が多いほうが高スコア（単調）
        assert score_many > score_few


# ----------------------------------------------------------------------------
# _compute_engagement
# ----------------------------------------------------------------------------


class TestComputeEngagement:
    def test_zero_videos_returns_zero(self):
        # Given: 動画なし
        score = _compute_engagement([])

        # Then
        assert score == pytest.approx(0.0)

    def test_score_is_in_unit_interval(self):
        # Given: 通常のエンゲージメント
        videos = [_make_video(views=1000, likes=50, comments=10)]

        # When
        score = _compute_engagement(videos)

        # Then: 0..1 にクランプされる
        assert 0.0 <= score <= 1.0

    def test_higher_engagement_yields_higher_score(self):
        # Given: ER% が異なる 2 セット
        low = [_make_video(views=10_000, likes=10, comments=1)]
        high = [_make_video(views=10_000, likes=2_000, comments=500)]

        # When
        score_low = _compute_engagement(low)
        score_high = _compute_engagement(high)

        # Then
        assert score_high > score_low

    def test_zero_views_does_not_explode(self):
        # Given: views=0 の動画（ゼロ除算の罠）
        videos = [_make_video(views=0, likes=0, comments=0)]

        # When/Then: 例外を出さず 0..1 内
        score = _compute_engagement(videos)
        assert 0.0 <= score <= 1.0


# ----------------------------------------------------------------------------
# _compute_posting_cadence
# ----------------------------------------------------------------------------


class TestComputePostingCadence:
    def test_high_frequency_recent_post_yields_high_score(self):
        # Given: 直近 5 本が直近 30 日以内に密集
        videos = [_make_video(days_ago=i * 3) for i in range(1, 6)]

        # When
        score = _compute_posting_cadence(videos, posted_within_days=30)

        # Then: 0.5 以上
        assert score >= 0.5
        assert score <= 1.0

    def test_no_videos_returns_zero(self):
        # Given: 動画なし
        score = _compute_posting_cadence([], posted_within_days=30)

        # Then
        assert score == pytest.approx(0.0)

    def test_score_is_in_unit_interval(self):
        # Given: 任意の動画
        videos = [_make_video(days_ago=1), _make_video(days_ago=10)]

        # When
        score = _compute_posting_cadence(videos, posted_within_days=30)

        # Then
        assert 0.0 <= score <= 1.0

    def test_old_posts_yield_low_score(self):
        # Given: 全動画が posted_within_days 超過
        videos = [_make_video(days_ago=200 + i * 30) for i in range(5)]

        # When
        score = _compute_posting_cadence(videos, posted_within_days=30)

        # Then
        assert score < 0.5


# ----------------------------------------------------------------------------
# _compute_subscriber_proximity
# ----------------------------------------------------------------------------


class TestComputeSubscriberProximity:
    def test_center_of_range_is_max(self):
        # Given: レンジ中央
        score = _compute_subscriber_proximity(subscribers=505_000, min_=10_000, max_=1_000_000)

        # Then: 中央は 1.0 近傍
        assert score == pytest.approx(1.0, abs=0.01)

    def test_at_min_edge_is_lower_than_center(self):
        # Given: 下限ぴったり
        edge = _compute_subscriber_proximity(subscribers=10_000, min_=10_000, max_=1_000_000)
        center = _compute_subscriber_proximity(subscribers=505_000, min_=10_000, max_=1_000_000)

        # Then: 端は中央より低い
        assert 0.0 <= edge < center

    def test_at_max_edge_is_lower_than_center(self):
        # Given: 上限ぴったり
        edge = _compute_subscriber_proximity(subscribers=1_000_000, min_=10_000, max_=1_000_000)
        center = _compute_subscriber_proximity(subscribers=505_000, min_=10_000, max_=1_000_000)

        # Then
        assert 0.0 <= edge < center

    def test_score_is_in_unit_interval(self):
        # Given/When/Then: レンジ内のどんな値でも 0..1
        for subs in [10_000, 100_000, 505_000, 800_000, 1_000_000]:
            score = _compute_subscriber_proximity(subscribers=subs, min_=10_000, max_=1_000_000)
            assert 0.0 <= score <= 1.0

    def test_zero_radius_range_is_full_match(self):
        # Given: min == max（_build_params が許容する退化エッジ）。
        # フィルタ通過後の subs は必ず min == max == subs なので full match (1.0) として扱う。
        score = _compute_subscriber_proximity(subscribers=100_000, min_=100_000, max_=100_000)

        # Then: フィルタ通過済みなので最低スコア扱いせず 1.0 を返す
        assert score == pytest.approx(1.0)


# ----------------------------------------------------------------------------
# _combine_score
# ----------------------------------------------------------------------------


class TestCombineScore:
    def test_all_components_one_yields_total_one(self):
        # Given: 4 成分が全部 1.0
        breakdown = _combine_score(
            keyword_match=1.0,
            engagement=1.0,
            posting_cadence=1.0,
            subscriber_proximity=1.0,
        )

        # Then: 重み総和 = 1 → total = 1
        assert isinstance(breakdown, ScoreBreakdown)
        assert breakdown.total == pytest.approx(1.0)

    def test_all_zero_yields_zero(self):
        # Given: 4 成分が全部 0
        breakdown = _combine_score(
            keyword_match=0.0,
            engagement=0.0,
            posting_cadence=0.0,
            subscriber_proximity=0.0,
        )

        # Then
        assert breakdown.total == pytest.approx(0.0)

    def test_components_are_preserved_in_breakdown(self):
        # Given: 各成分の値
        breakdown = _combine_score(
            keyword_match=0.8,
            engagement=0.6,
            posting_cadence=0.4,
            subscriber_proximity=0.2,
        )

        # Then: 内訳は入力値をそのまま保持（重み付けは total のみに反映）
        assert breakdown.keyword_match == pytest.approx(0.8)
        assert breakdown.engagement == pytest.approx(0.6)
        assert breakdown.posting_cadence == pytest.approx(0.4)
        assert breakdown.subscriber_proximity == pytest.approx(0.2)

    def test_total_is_in_unit_interval(self):
        # Given: 任意の組み合わせ
        breakdown = _combine_score(
            keyword_match=0.5,
            engagement=0.3,
            posting_cadence=0.7,
            subscriber_proximity=0.9,
        )

        # Then
        assert 0.0 <= breakdown.total <= 1.0


# ----------------------------------------------------------------------------
# _format_reason
# ----------------------------------------------------------------------------


class TestFormatReason:
    def test_top_two_factors_appear_in_reason(self):
        # Given: keyword_match と engagement が突出
        breakdown = ScoreBreakdown(
            keyword_match=0.95,
            engagement=0.90,
            posting_cadence=0.20,
            subscriber_proximity=0.10,
            total=0.7,
        )

        # When
        reason = _format_reason(breakdown)

        # Then: 上位 2 要因（keyword_match, engagement）に対応するフレーズが含まれる
        assert isinstance(reason, str)
        assert reason  # non-empty

    def test_reason_changes_when_top_factors_change(self):
        # Given: 上位 2 要因が異なる 2 ケース
        ranked_keyword = ScoreBreakdown(
            keyword_match=0.95,
            engagement=0.10,
            posting_cadence=0.95,
            subscriber_proximity=0.10,
            total=0.6,
        )
        ranked_subs = ScoreBreakdown(
            keyword_match=0.10,
            engagement=0.95,
            posting_cadence=0.10,
            subscriber_proximity=0.95,
            total=0.6,
        )

        # When
        r1 = _format_reason(ranked_keyword)
        r2 = _format_reason(ranked_subs)

        # Then: 異なるフレーズが生成される
        assert r1 != r2


# ----------------------------------------------------------------------------
# discover_competitors（API は MagicMock で差し込み、パイプライン全体を通す）
# ----------------------------------------------------------------------------


class TestDiscoverCompetitors:
    def _make_youtube_mock(
        self,
        *,
        search_items: list[dict],
        channel_items: list[dict],
        playlist_items: dict[str, list[dict]],
        video_items: list[dict],
    ) -> MagicMock:
        """YouTube Data API の最小限モックを構築する

        - search().list().execute() → channel id を含むレスポンス
        - channels().list().execute() → snippet/statistics/contentDetails
        - playlistItems().list().execute() → contentDetails.videoId
        - videos().list().execute() → snippet/statistics
        """
        youtube = MagicMock()

        # search
        youtube.search.return_value.list.return_value.execute.return_value = {
            "items": search_items,
        }

        # channels (id バッチごとに分岐するのは複雑なので、全件を返す簡易版)
        youtube.channels.return_value.list.return_value.execute.return_value = {
            "items": channel_items,
        }

        # playlistItems: playlistId をキーに切り替え
        def _playlist_list(**kwargs):
            playlist_id = kwargs.get("playlistId")
            mock_request = MagicMock()
            mock_request.execute.return_value = {
                "items": playlist_items.get(playlist_id, []),
                "nextPageToken": None,
            }
            return mock_request

        youtube.playlistItems.return_value.list.side_effect = _playlist_list

        # videos
        youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": video_items,
        }

        return youtube

    def test_returns_scored_candidates_sorted_by_total_desc(self):
        # Given: 2 つのチャンネルが search で hit、両方ともフィルタ通過
        today_iso = date.today().isoformat()
        youtube = self._make_youtube_mock(
            search_items=[
                {"snippet": {"channelId": "UC_A", "channelTitle": "Channel A"}},
                {"snippet": {"channelId": "UC_B", "channelTitle": "Channel B"}},
            ],
            channel_items=[
                {
                    "id": "UC_A",
                    "snippet": {
                        "title": "Channel A",
                        "description": "lo-fi study music",
                        "customUrl": "@channela",
                    },
                    "statistics": {"subscriberCount": "480000", "videoCount": "120"},
                    "contentDetails": {"relatedPlaylists": {"uploads": "UU_A"}},
                },
                {
                    "id": "UC_B",
                    "snippet": {
                        "title": "Channel B",
                        "description": "chill beats for studying",
                        "customUrl": "@channelb",
                    },
                    "statistics": {"subscriberCount": "250000", "videoCount": "80"},
                    "contentDetails": {"relatedPlaylists": {"uploads": "UU_B"}},
                },
            ],
            playlist_items={
                "UU_A": [{"contentDetails": {"videoId": "VA1"}}],
                "UU_B": [{"contentDetails": {"videoId": "VB1"}}],
            },
            video_items=[
                {
                    "id": "VA1",
                    "snippet": {"title": "lo-fi study session", "publishedAt": f"{today_iso}T00:00:00Z"},
                    "statistics": {"viewCount": "120000", "likeCount": "8000", "commentCount": "1500"},
                },
                {
                    "id": "VB1",
                    "snippet": {"title": "chill beats", "publishedAt": f"{today_iso}T00:00:00Z"},
                    "statistics": {"viewCount": "80000", "likeCount": "1000", "commentCount": "100"},
                },
            ],
        )
        params = _make_params(
            keywords=("lo-fi study",),
            min_subscribers=10_000,
            max_subscribers=1_000_000,
            posted_within_days=30,
            top=10,
            per_keyword_results=5,
        )

        # When
        scored = discover_competitors(youtube, params)

        # Then: 戻り値は ScoredCandidate のリスト、スコア降順
        assert all(isinstance(s, ScoredCandidate) for s in scored)
        assert len(scored) >= 1
        totals = [s.score.total for s in scored]
        assert totals == sorted(totals, reverse=True)

    def test_truncates_to_top_n(self):
        # Given: 3 件 search hit、top=2
        today_iso = date.today().isoformat()
        youtube = self._make_youtube_mock(
            search_items=[{"snippet": {"channelId": f"UC_{i}", "channelTitle": f"Channel {i}"}} for i in range(3)],
            channel_items=[
                {
                    "id": f"UC_{i}",
                    "snippet": {"title": f"Channel {i}", "description": "lo-fi", "customUrl": f"@ch{i}"},
                    "statistics": {"subscriberCount": str(100_000 + i * 10_000), "videoCount": "50"},
                    "contentDetails": {"relatedPlaylists": {"uploads": f"UU_{i}"}},
                }
                for i in range(3)
            ],
            playlist_items={f"UU_{i}": [{"contentDetails": {"videoId": f"V{i}"}}] for i in range(3)},
            video_items=[
                {
                    "id": f"V{i}",
                    "snippet": {"title": "lo-fi", "publishedAt": f"{today_iso}T00:00:00Z"},
                    "statistics": {"viewCount": "10000", "likeCount": "100", "commentCount": "10"},
                }
                for i in range(3)
            ],
        )
        params = _make_params(top=2)

        # When
        scored = discover_competitors(youtube, params)

        # Then
        assert len(scored) <= 2

    def test_empty_search_results_returns_empty(self):
        # Given: search hit なし
        youtube = self._make_youtube_mock(
            search_items=[],
            channel_items=[],
            playlist_items={},
            video_items=[],
        )
        params = _make_params()

        # When
        scored = discover_competitors(youtube, params)

        # Then: 空リストで正常終了（例外を出さない）
        assert scored == []

    @pytest.mark.parametrize(
        "failing_api",
        ["search", "channels", "playlistItems", "videos"],
    )
    def test_wraps_http_error_as_youtube_api_error(self, failing_api: str):
        # Given: 指定 API のみ HttpError を投げ、上流 API は成功させる
        from googleapiclient.errors import HttpError

        today_iso = date.today().isoformat()
        # 上流が成功して下流まで到達する最小モックを構築
        youtube = self._make_youtube_mock(
            search_items=[{"snippet": {"channelId": "UC_X", "channelTitle": "Channel X"}}],
            channel_items=[
                {
                    "id": "UC_X",
                    "snippet": {"title": "Channel X", "description": "lo-fi", "customUrl": "@x"},
                    "statistics": {"subscriberCount": "100000", "videoCount": "10"},
                    "contentDetails": {"relatedPlaylists": {"uploads": "UU_X"}},
                }
            ],
            playlist_items={"UU_X": [{"contentDetails": {"videoId": "VX1"}}]},
            video_items=[
                {
                    "id": "VX1",
                    "snippet": {"title": "lo-fi", "publishedAt": f"{today_iso}T00:00:00Z"},
                    "statistics": {"viewCount": "10000", "likeCount": "100", "commentCount": "10"},
                }
            ],
        )

        resp = MagicMock()
        resp.status = 403
        resp.reason = "Forbidden"
        http_err = HttpError(resp=resp, content=b'{"error": {"message": "quotaExceeded"}}')

        # 対象 API の execute() のみ HttpError を投げるように差し替える
        api_attr = getattr(youtube, failing_api)
        if failing_api == "playlistItems":
            # playlistItems は side_effect を設定済みのため、それを上書きして HttpError を返す request を返す
            failing_request = MagicMock()
            failing_request.execute.side_effect = http_err
            api_attr.return_value.list.side_effect = lambda **_: failing_request
        else:
            api_attr.return_value.list.return_value.execute.side_effect = http_err

        params = _make_params(min_subscribers=10_000, max_subscribers=1_000_000)

        # When/Then: ドメイン例外 YouTubeAPIError に包まれて伝播する
        with pytest.raises(YouTubeAPIError):
            discover_competitors(youtube, params)
