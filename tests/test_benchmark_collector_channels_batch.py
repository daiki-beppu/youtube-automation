"""`BenchmarkCollector` の `channels.list` 50 件バッチ化（Issue #310）のユニットテスト

検証対象:
- `_fetch_channels_metadata` がカンマ区切りバッチで `youtube.channels().list` を呼ぶ
- 50 件超のとき `_CHANNELS_BATCH_SIZE` 単位に分割して複数回呼ばれる
- `collect_all` が `_fetch_channels_metadata` をループ前に 1 回プリフェッチし、
  `collect_channel` には API 個別呼び出しを行わせない
- `ch_item` が空のとき `collect_channel` は空辞書を返す（既存挙動）

ネットワークも YouTube API も呼ばない（MagicMock で差し込み）。
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from youtube_automation.infrastructure.errors import YouTubeAPIError
from youtube_automation.scripts.benchmark_collector import (
    _CHANNELS_BATCH_SIZE,
    BenchmarkCollector,
    BenchmarkReportGenerator,
)


def _make_collector(youtube_mock: MagicMock, *, benchmark_channels: list[dict] | None = None) -> BenchmarkCollector:
    """設定をロードした `BenchmarkCollector` に youtube モックを差し込む。

    `benchmark_channels` を渡すと、`config.analytics.benchmark.channels` を上書きしたい
    `collect_all` 系テストで使う。`Benchmark` dataclass が frozen のため、`SimpleNamespace`
    で同形のアクセスパスを構築して差し替える。
    """
    collector = BenchmarkCollector()
    collector.youtube = youtube_mock
    if benchmark_channels is not None:
        collector.config = SimpleNamespace(
            analytics=SimpleNamespace(
                benchmark=SimpleNamespace(channels=benchmark_channels),
            ),
        )
    return collector


def _ch_item(channel_id: str, *, uploads: str = "UU_DUMMY") -> dict:
    """`channels.list` レスポンス item の最小モック。"""
    return {
        "id": channel_id,
        "snippet": {"title": channel_id},
        "statistics": {"subscriberCount": "1000", "videoCount": "10"},
        "contentDetails": {"relatedPlaylists": {"uploads": uploads}},
    }


def _video_item(
    video_id: str,
    *,
    title: str = "Benchmark Video",
    description: str = "",
    view_count: str = "20000",
    duration: str = "PT1H30M",
    published_at: str = "2026-05-01T12:00:00Z",
    thumbnails: dict | None = None,
) -> dict:
    return {
        "id": video_id,
        "snippet": {
            "title": title,
            "publishedAt": published_at,
            "description": description,
            "tags": ["ambient", "study"],
            "thumbnails": thumbnails
            if thumbnails is not None
            else {"high": {"url": f"https://example.com/{video_id}.jpg"}},
        },
        "statistics": {
            "viewCount": view_count,
            "likeCount": "1000",
            "commentCount": "25",
        },
        "contentDetails": {"duration": duration},
    }


class TestFetchChannelsMetadata:
    def test_retries_transient_api_failure_through_benchmark_collector(self, monkeypatch):
        monkeypatch.setattr("youtube_automation.infrastructure.retry.time.sleep", lambda _: None)
        youtube = MagicMock()
        transient = HttpError(Response({"status": "503"}), b'{"error": {"errors": [{"reason": "backendError"}]}}')
        request = youtube.channels.return_value.list.return_value
        request.execute.side_effect = [transient, {"items": [_ch_item("UC_OK")]}]
        collector = _make_collector(youtube)

        result = collector._fetch_channels_metadata([{"id": "UC_OK"}])

        assert result == {"UC_OK": _ch_item("UC_OK")}
        assert request.execute.call_count == 2

    def test_single_batch_uses_comma_separated_ids(self):
        # Given: 3 チャンネル分の channel_info
        channel_infos = [{"id": f"UC_{i}", "name": f"ch{i}", "slug": f"s{i}"} for i in range(3)]
        youtube = MagicMock()
        youtube.channels.return_value.list.return_value.execute.return_value = {
            "items": [_ch_item(f"UC_{i}") for i in range(3)],
        }
        collector = _make_collector(youtube)

        # When
        result = collector._fetch_channels_metadata(channel_infos)

        # Then: 1 回だけ呼ばれ、id がカンマ区切りで渡される
        assert youtube.channels.return_value.list.call_count == 1
        call_kwargs = youtube.channels.return_value.list.call_args.kwargs
        assert call_kwargs["id"] == "UC_0,UC_1,UC_2"
        assert call_kwargs["part"] == "snippet,statistics,contentDetails"
        # 戻り値は channel_id → item のマップ
        assert set(result.keys()) == {"UC_0", "UC_1", "UC_2"}
        assert result["UC_0"]["id"] == "UC_0"

    def test_batches_above_limit_split_into_multiple_calls(self):
        # Given: _CHANNELS_BATCH_SIZE + 5 件 = 2 バッチ
        n = _CHANNELS_BATCH_SIZE + 5
        channel_infos = [{"id": f"UC_{i}", "name": f"ch{i}", "slug": f"s{i}"} for i in range(n)]
        youtube = MagicMock()

        # バッチごとに該当 ID 分のアイテムを返す
        def _list(**kwargs):
            ids = kwargs["id"].split(",")
            mock_request = MagicMock()
            mock_request.execute.return_value = {"items": [_ch_item(cid) for cid in ids]}
            return mock_request

        youtube.channels.return_value.list.side_effect = _list
        collector = _make_collector(youtube)

        # When
        result = collector._fetch_channels_metadata(channel_infos)

        # Then: 2 回呼ばれ、それぞれのバッチサイズが 50 / 5
        assert youtube.channels.return_value.list.call_count == 2
        first_ids = youtube.channels.return_value.list.call_args_list[0].kwargs["id"].split(",")
        second_ids = youtube.channels.return_value.list.call_args_list[1].kwargs["id"].split(",")
        assert len(first_ids) == _CHANNELS_BATCH_SIZE
        assert len(second_ids) == 5
        # 全件分の item が返る
        assert len(result) == n

    def test_missing_channel_id_not_in_result(self):
        # Given: 2 件リクエストしたが API レスポンスには 1 件しか含まれない
        channel_infos = [
            {"id": "UC_OK", "name": "ok", "slug": "ok"},
            {"id": "UC_DELETED", "name": "deleted", "slug": "deleted"},
        ]
        youtube = MagicMock()
        youtube.channels.return_value.list.return_value.execute.return_value = {
            "items": [_ch_item("UC_OK")],
        }
        collector = _make_collector(youtube)

        # When
        result = collector._fetch_channels_metadata(channel_infos)

        # Then: 削除済み channel_id はキーに現れない（呼び出し側が `.get(..., {})` で扱う契約）
        assert "UC_OK" in result
        assert "UC_DELETED" not in result

    def test_empty_input_makes_no_api_call(self):
        # Given: 空入力
        youtube = MagicMock()
        collector = _make_collector(youtube)

        # When
        result = collector._fetch_channels_metadata([])

        # Then: API は呼ばれず空辞書
        youtube.channels.return_value.list.assert_not_called()
        assert result == {}


class TestCollectChannelWithPrefetchedItem:
    def test_raises_when_ch_item_is_empty(self):
        # Given: 上位で API レスポンスに含まれていなかったケースを模倣
        youtube = MagicMock()
        collector = _make_collector(youtube)

        # When / Then: 空辞書で握りつぶさず欠落を例外で伝播（issue #619）
        with pytest.raises(YouTubeAPIError, match="UC_X"):
            collector.collect_channel({"id": "UC_X", "name": "x", "slug": "x"}, {})

        # channels.list は再呼び出ししない（プリフェッチ済みの契約）
        youtube.channels.return_value.list.assert_not_called()

    def test_does_not_call_channels_list_when_ch_item_provided(self):
        # Given: ch_item を渡し、playlistItems / videos は空応答にする
        youtube = MagicMock()
        youtube.playlistItems.return_value.list.return_value.execute.return_value = {
            "items": [],
            "nextPageToken": None,
        }
        collector = _make_collector(youtube)
        ch_item = _ch_item("UC_OK", uploads="UU_OK")

        # When
        result = collector.collect_channel({"id": "UC_OK", "name": "ok", "slug": "ok"}, ch_item)

        # Then: ch_item 経由でメタデータを参照、channels.list は呼ばれない
        youtube.channels.return_value.list.assert_not_called()
        assert result["channel_id"] == "UC_OK"
        assert result["subscribers"] == 1000

    def test_preserves_full_description_on_collected_video(self):
        # Given: 動画詳細 API が TTP 対象になる概要欄本文を返す
        description = (
            "A calm opening paragraph for late-night focus.\n\n"
            "In this mix, you'll find:\n"
            "- Warm keys and soft tape texture\n\n"
            "Tracklist:\n"
            "00:00 - First Theme\n"
            "08:12 - Second Theme\n\n"
            "Subscribe for more sessions.\n"
            "#DeepFocus #AmbientStudy"
        )
        youtube = MagicMock()
        youtube.playlistItems.return_value.list.return_value.execute.return_value = {
            "items": [{"contentDetails": {"videoId": "VID_FULL_DESC"}}],
            "nextPageToken": None,
        }
        youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": [_video_item("VID_FULL_DESC", description=description)],
        }
        collector = _make_collector(youtube)
        collector.benchmark_config = {"scan_recent": 1, "min_views": 10000}

        # When
        result = collector.collect_channel({"id": "UC_OK", "name": "ok", "slug": "ok"}, _ch_item("UC_OK"))

        # Then: playlist 系パスと同じ `description` キーで本文を保持し、既存キーワードも維持する
        video = result["videos"][0]
        assert video["description"] == description
        assert "description_keywords" in video
        assert "ambientstudy" in video["description_keywords"]

    def test_upload_scan_keeps_pre_filter_videos_and_marks_exhausted_playlist_complete(self):
        youtube = MagicMock()
        youtube.playlistItems.return_value.list.return_value.execute.return_value = {
            "items": [
                {"contentDetails": {"videoId": "VID_LOW"}},
                {"contentDetails": {"videoId": "VID_HIGH"}},
            ],
            "nextPageToken": None,
        }
        youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": [
                _video_item("VID_LOW", view_count="3200", published_at="2026-07-10T12:00:00Z"),
                _video_item("VID_HIGH", view_count="20000", published_at="2026-01-02T12:00:00Z"),
            ],
        }
        collector = _make_collector(youtube)
        collector.benchmark_config = {"scan_recent": 50, "min_views": 10000}

        result = collector.collect_channel({"id": "UC_OK", "name": "ok", "slug": "ok"}, _ch_item("UC_OK"))

        assert [video["video_id"] for video in result["videos"]] == ["VID_HIGH"]
        assert result["upload_scan"] == {
            "scanned_count": 2,
            "complete": True,
            "latest_upload_at": "2026-07-10",
            "oldest_upload_at": "2026-01-02",
            "videos": [
                {"published_at": "2026-07-10", "views": 3200},
                {"published_at": "2026-01-02", "views": 20000},
            ],
        }

    def test_upload_scan_is_incomplete_when_scan_limit_stops_pagination(self):
        youtube = MagicMock()
        youtube.playlistItems.return_value.list.return_value.execute.return_value = {
            "items": [{"contentDetails": {"videoId": "VID_1"}}],
            "nextPageToken": "MORE",
        }
        youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": [_video_item("VID_1")],
        }
        collector = _make_collector(youtube)
        collector.benchmark_config = {"scan_recent": 1, "min_views": 10000}

        result = collector.collect_channel({"id": "UC_OK", "name": "ok", "slug": "ok"}, _ch_item("UC_OK"))

        assert result["upload_scan"]["complete"] is False

    @pytest.mark.parametrize(
        ("wide_thumbnails", "expected_url"),
        [
            (
                {
                    "high": {"url": "https://example.com/short-high-wide.jpg"},
                    "medium": {"url": "https://example.com/short-medium-wide.jpg"},
                    "default": {"url": "https://example.com/short-default-wide.jpg"},
                },
                "https://example.com/short-high-wide.jpg",
            ),
            (
                {"high": {"url": "https://example.com/short-high-wide.jpg"}},
                "https://example.com/short-high-wide.jpg",
            ),
            (
                {
                    "medium": {"url": "https://example.com/short-medium-wide.jpg"},
                    "default": {"url": "https://example.com/short-default-wide.jpg"},
                },
                "https://example.com/short-medium-wide.jpg",
            ),
            (
                {"medium": {"url": "https://example.com/short-medium-wide.jpg"}},
                "https://example.com/short-medium-wide.jpg",
            ),
            (
                {"default": {"url": "https://example.com/short-default-wide.jpg"}},
                "https://example.com/short-default-wide.jpg",
            ),
            ({}, ""),
        ],
    )
    def test_short_video_thumbnail_uses_wide_key_not_maxres_or_standard(self, wide_thumbnails, expected_url):
        youtube = MagicMock()
        youtube.playlistItems.return_value.list.return_value.execute.return_value = {
            "items": [{"contentDetails": {"videoId": "VID_SHORT"}}],
            "nextPageToken": None,
        }
        thumbnails = {
            "maxres": {"url": "https://example.com/short-maxres-vertical.jpg"},
            "standard": {"url": "https://example.com/short-standard-vertical.jpg"},
            **wide_thumbnails,
        }
        youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": [
                _video_item(
                    "VID_SHORT",
                    duration="PT45S",
                    thumbnails=thumbnails,
                )
            ],
        }
        collector = _make_collector(youtube)
        collector.benchmark_config = {"scan_recent": 1, "min_views": 10000}

        result = collector.collect_channel({"id": "UC_OK", "name": "ok", "slug": "ok"}, _ch_item("UC_OK"))

        video = result["videos"][0]
        assert video["duration_iso"] == "PT45S"
        assert video["thumbnail_url"] == expected_url
        assert result["avg_views"] == 0
        assert result["avg_daily_views"] == 0
        assert result["avg_engagement_rate"] == 0

    def test_long_video_thumbnail_keeps_maxres_priority(self):
        youtube = MagicMock()
        youtube.playlistItems.return_value.list.return_value.execute.return_value = {
            "items": [{"contentDetails": {"videoId": "VID_LONG"}}],
            "nextPageToken": None,
        }
        youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": [
                _video_item(
                    "VID_LONG",
                    duration="PT1H30M",
                    thumbnails={
                        "maxres": {"url": "https://example.com/long-maxres.jpg"},
                        "standard": {"url": "https://example.com/long-standard.jpg"},
                        "high": {"url": "https://example.com/long-high.jpg"},
                    },
                )
            ],
        }
        collector = _make_collector(youtube)
        collector.benchmark_config = {"scan_recent": 1, "min_views": 10000}

        result = collector.collect_channel({"id": "UC_OK", "name": "ok", "slug": "ok"}, _ch_item("UC_OK"))

        video = result["videos"][0]
        assert video["duration_iso"] == "PT1H30M"
        assert video["thumbnail_url"] == "https://example.com/long-maxres.jpg"


class TestCollectAllPrefetchesChannels:
    def test_collect_all_prefetches_metadata_in_single_batch(self):
        # Given: 2 チャンネル、playlistItems も videos も空応答
        channels_cfg = [
            {"id": "UC_A", "name": "A", "slug": "a"},
            {"id": "UC_B", "name": "B", "slug": "b"},
        ]
        youtube = MagicMock()
        youtube.channels.return_value.list.return_value.execute.return_value = {
            "items": [_ch_item("UC_A", uploads="UU_A"), _ch_item("UC_B", uploads="UU_B")],
        }
        youtube.playlistItems.return_value.list.return_value.execute.return_value = {
            "items": [],
            "nextPageToken": None,
        }
        collector = _make_collector(youtube, benchmark_channels=channels_cfg)

        # When: force=True で全件取得経路を回す
        data = collector.collect_all(force=True)

        # Then: channels.list は 1 回（バッチ呼び出し）、id はカンマ区切り
        assert youtube.channels.return_value.list.call_count == 1
        call_kwargs = youtube.channels.return_value.list.call_args.kwargs
        assert call_kwargs["id"] == "UC_A,UC_B"
        # 2 チャンネル分の結果が返る
        assert len(data["channels"]) == 2
        assert {c["channel_id"] for c in data["channels"]} == {"UC_A", "UC_B"}

    def test_collect_all_raises_when_channel_missing_from_api(self):
        # Given: 設定上は 2 件だが API は 1 件のみ返す（片方は削除済み等）
        channels_cfg = [
            {"id": "UC_OK", "name": "ok", "slug": "ok"},
            {"id": "UC_DEL", "name": "del", "slug": "del"},
        ]
        youtube = MagicMock()
        youtube.channels.return_value.list.return_value.execute.return_value = {
            "items": [_ch_item("UC_OK", uploads="UU_OK")],
        }
        youtube.playlistItems.return_value.list.return_value.execute.return_value = {
            "items": [],
            "nextPageToken": None,
        }
        collector = _make_collector(youtube, benchmark_channels=channels_cfg)

        # When / Then: 欠落を黙ってスキップせず収集失敗として停止（issue #619）
        with pytest.raises(YouTubeAPIError, match="UC_DEL"):
            collector.collect_all(force=True)


class TestBenchmarkReportGeneratorDescriptionSamples:
    def test_channel_markdown_includes_description_ttp_samples(self, tmp_path):
        # Given: benchmark JSON 相当の channel data に概要欄本文つき Long 動画がある
        description = (
            "A direct prose hook that should be visible in the benchmark report.\n\n"
            "In this mix, you'll find:\n"
            "- Warm keys\n"
            "- Slow dusty drums\n\n"
            "Tracklist:\n"
            "00:00 - First Theme\n"
            "08:12 - Second Theme\n\n"
            "Subscribe for more sessions.\n"
            "#DeepFocus #AmbientStudy"
        )
        channel = {
            "name": "Reference Channel",
            "channel_id": "UC_REF",
            "slug": "reference",
            "collected_at": "2026-05-28",
            "subscribers": 120000,
            "total_videos": 80,
            "relationship": "TTP target",
            "min_views_threshold": 10000,
            "scanned_count": 1,
            "avg_views": 50000,
            "avg_daily_views": 1000,
            "avg_engagement_rate": 2.1,
            "posting_trend": {},
            "top_tags": [],
            "videos": [
                {
                    "video_id": "VID_REF",
                    "title": "Reference Mix",
                    "published_at": "2026-05-01",
                    "published_at_utc": "2026-05-01T12:00:00Z",
                    "views": 50000,
                    "daily_views": 1000.0,
                    "likes": 1000,
                    "comments": 50,
                    "engagement_rate": 2.1,
                    "duration_iso": "PT1H30M",
                    "duration_display": "1h30m",
                    "tags": [],
                    "description": description,
                    "description_keywords": ["ambientstudy"],
                    "thumbnail_analysis": None,
                }
            ],
        }
        config = SimpleNamespace(analytics=SimpleNamespace(benchmark=SimpleNamespace(channels=[])))
        generator = BenchmarkReportGenerator(config, tmp_path, date(2026, 5, 28))

        # When
        markdown = generator._generate_channel_md(channel)

        # Then: docs/benchmarks/*.md から概要欄の型を参照できる
        assert "## 概要欄TTPサンプル" in markdown
        assert "Reference Mix" in markdown
        assert "A direct prose hook that should be visible in the benchmark report." in markdown
        assert "Tracklist:" in markdown
        assert "#DeepFocus #AmbientStudy" in markdown

    def test_channel_markdown_uses_longer_fence_when_description_contains_backticks(self, tmp_path):
        description = "Opening hook.\n\n```text\nexample block\n```\n\nTracklist:\n00:00 - First"
        channel = {
            "name": "Reference Channel",
            "channel_id": "UC_REF",
            "slug": "reference",
            "collected_at": "2026-05-28",
            "subscribers": 120000,
            "total_videos": 80,
            "relationship": "TTP target",
            "min_views_threshold": 10000,
            "scanned_count": 1,
            "avg_views": 50000,
            "avg_daily_views": 1000,
            "avg_engagement_rate": 2.1,
            "posting_trend": {},
            "top_tags": [],
            "videos": [
                {
                    "video_id": "VID_REF",
                    "title": "Reference Mix",
                    "published_at": "2026-05-01",
                    "published_at_utc": "2026-05-01T12:00:00Z",
                    "views": 50000,
                    "daily_views": 1000.0,
                    "likes": 1000,
                    "comments": 50,
                    "engagement_rate": 2.1,
                    "duration_iso": "PT1H30M",
                    "duration_display": "1h30m",
                    "tags": [],
                    "description": description,
                    "description_keywords": ["ambientstudy"],
                    "thumbnail_analysis": None,
                }
            ],
        }
        config = SimpleNamespace(analytics=SimpleNamespace(benchmark=SimpleNamespace(channels=[])))
        generator = BenchmarkReportGenerator(config, tmp_path, date(2026, 5, 28))

        markdown = generator._generate_channel_md(channel)

        assert "\n````text\n" in markdown
        assert "\n````\n" in markdown
        assert description in markdown

    def test_channel_markdown_omits_description_samples_when_all_descriptions_empty(self, tmp_path):
        # Given: 動画はあるが概要欄本文が保存されていない channel data
        channel = {
            "name": "Reference Channel",
            "channel_id": "UC_REF",
            "slug": "reference",
            "collected_at": "2026-05-28",
            "subscribers": 120000,
            "total_videos": 80,
            "relationship": "TTP target",
            "min_views_threshold": 10000,
            "scanned_count": 1,
            "avg_views": 50000,
            "avg_daily_views": 1000,
            "avg_engagement_rate": 2.1,
            "posting_trend": {},
            "top_tags": [],
            "videos": [
                {
                    "video_id": "VID_EMPTY",
                    "title": "Reference Mix",
                    "published_at": "2026-05-01",
                    "published_at_utc": "2026-05-01T12:00:00Z",
                    "views": 50000,
                    "daily_views": 1000.0,
                    "likes": 1000,
                    "comments": 50,
                    "engagement_rate": 2.1,
                    "duration_iso": "PT1H30M",
                    "duration_display": "1h30m",
                    "tags": [],
                    "description": "",
                    "description_keywords": [],
                    "thumbnail_analysis": None,
                }
            ],
        }
        config = SimpleNamespace(analytics=SimpleNamespace(benchmark=SimpleNamespace(channels=[])))
        generator = BenchmarkReportGenerator(config, tmp_path, date(2026, 5, 28))

        # When
        markdown = generator._generate_channel_md(channel)

        # Then: 空の概要欄セクションを作らない
        assert "## 概要欄TTPサンプル" not in markdown
