"""ベンチマーク未取得・空・取得失敗時の fallback 是正（issue #619）のユニットテスト

検証対象（「実データが無いなら止まる／明示的に知らせる」原則）:
- `load_benchmark_videos`: JSON 未検出 / フィルタ後 0 件 → `ConfigError`
- `collect_channel`: チャンネル欠落 → `YouTubeAPIError` / API 失敗 → `YouTubeAPIError`
- `collect_all`: 欠落チャンネルを黙殺せず `YouTubeAPIError` / 未登録 slug → `ConfigError`
- `_fetch_channels_metadata`: HttpError → `YouTubeAPIError`
- `ensure_benchmark_fresh`: benchmark.channels 未設定 → `ConfigError`

ネットワークも YouTube API も呼ばない（MagicMock / HttpError で差し込み）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from youtube_automation.infrastructure.errors import ConfigError, YouTubeAPIError
from youtube_automation.scripts.benchmark_collector import (
    BenchmarkCollector,
    is_live_benchmark_video,
    load_benchmark_videos,
)


def _http_error(status: int = 403, reason: str = "quotaExceeded") -> HttpError:
    """`from_http_error` が解釈できる最小の HttpError を組み立てる。"""
    resp = SimpleNamespace(status=status, reason="Forbidden")
    content = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode("utf-8")
    return HttpError(resp, content)


def _make_collector(youtube_mock: MagicMock, *, benchmark_channels: list[dict] | None = None) -> BenchmarkCollector:
    collector = BenchmarkCollector()
    collector.youtube = youtube_mock
    if benchmark_channels is not None:
        collector.config = SimpleNamespace(
            analytics=SimpleNamespace(benchmark=SimpleNamespace(channels=benchmark_channels)),
        )
    return collector


def _ch_item(channel_id: str, *, uploads: str = "UU_DUMMY") -> dict:
    return {
        "id": channel_id,
        "snippet": {"title": channel_id},
        "statistics": {"subscriberCount": "1000", "videoCount": "10"},
        "contentDetails": {"relatedPlaylists": {"uploads": uploads}},
    }


def _write_benchmark_json(data_dir, channels: list[dict]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "benchmark_20260531.json"
    path.write_text(json.dumps({"channels": channels}), encoding="utf-8")


class TestLoadBenchmarkVideos:
    def test_raises_when_json_missing(self, tmp_path):
        # Given: data_dir に benchmark JSON が存在しない
        # When / Then: 空リストを返さず ConfigError で停止（次アクションを案内）
        with pytest.raises(ConfigError, match="benchmark"):
            load_benchmark_videos(tmp_path)

    def test_raises_when_no_video_meets_threshold(self, tmp_path):
        # Given: 動画はあるが min_views 未満ばかり
        _write_benchmark_json(
            tmp_path,
            [{"name": "ch", "slug": "ch", "videos": [{"video_id": "v1", "views": 500}]}],
        )

        # When / Then: フィルタ後 0 件は空リストを返さず ConfigError
        with pytest.raises(ConfigError, match="再生以上"):
            load_benchmark_videos(tmp_path, min_views=10000)

    def test_returns_videos_when_data_present(self, tmp_path):
        # Given: しきい値以上の動画がある（正常系は従来どおりリストを返す）
        _write_benchmark_json(
            tmp_path,
            [
                {
                    "name": "ch",
                    "slug": "ch",
                    "videos": [
                        {"video_id": "v1", "views": 50000, "title": "A", "thumbnail_url": "u"},
                        {"video_id": "v2", "views": 20000, "title": "B", "thumbnail_url": "u"},
                    ],
                }
            ],
        )

        result = load_benchmark_videos(tmp_path, min_views=10000)

        assert [v["video_id"] for v in result] == ["v1", "v2"]

    def test_filters_videos_by_competitor_slug(self, tmp_path):
        _write_benchmark_json(
            tmp_path,
            [
                {"name": "A", "slug": "a", "videos": [{"video_id": "a1", "views": 50000}]},
                {"name": "B", "slug": "b", "videos": [{"video_id": "b1", "views": 40000}]},
            ],
        )

        result = load_benchmark_videos(tmp_path, competitor_slug="b")

        assert [(video["video_id"], video["channel_slug"]) for video in result] == [("b1", "b")]

    def test_passes_through_duration_iso_for_live_detection(self, tmp_path):
        # Given: live 配信 (P0D) と VOD が混在。duration_iso 無しの旧形式は "" になる
        _write_benchmark_json(
            tmp_path,
            [
                {
                    "name": "ch",
                    "slug": "ch",
                    "videos": [
                        {"video_id": "live1", "views": 50000, "duration_iso": "P0D"},
                        {"video_id": "vod1", "views": 40000, "duration_iso": "PT1H"},
                        {"video_id": "old1", "views": 30000},
                    ],
                }
            ],
        )

        result = load_benchmark_videos(tmp_path, min_views=10000)

        by_id = {v["video_id"]: v for v in result}
        assert by_id["live1"]["duration_iso"] == "P0D"
        assert by_id["vod1"]["duration_iso"] == "PT1H"
        assert by_id["old1"]["duration_iso"] == ""
        assert is_live_benchmark_video(by_id["live1"])
        assert not is_live_benchmark_video(by_id["vod1"])
        assert not is_live_benchmark_video(by_id["old1"])


class TestCollectChannelFailures:
    def test_raises_when_channel_missing(self):
        # Given: API レスポンスに該当チャンネルが含まれなかった（空 ch_item）
        collector = _make_collector(MagicMock())

        # When / Then: 空辞書ではなく YouTubeAPIError
        with pytest.raises(YouTubeAPIError, match="UC_MISS"):
            collector.collect_channel({"id": "UC_MISS", "name": "miss", "slug": "miss"}, {})

    def test_wraps_http_error_from_playlist_items(self, no_retry_backoff):
        # Given: playlistItems 取得で HttpError（クォータ超過等）
        youtube = MagicMock()
        youtube.playlistItems.return_value.list.return_value.execute.side_effect = _http_error()
        collector = _make_collector(youtube)

        # When / Then: 生 HttpError ではなくドメイン例外に変換して伝播
        with pytest.raises(YouTubeAPIError) as exc:
            collector.collect_channel({"id": "UC_OK", "name": "ok", "slug": "ok"}, _ch_item("UC_OK"))
        assert exc.value.status_code == 403
        assert exc.value.reason == "quotaExceeded"


class TestCollectAllFailures:
    def test_raises_config_error_when_slug_not_registered(self):
        # Given: 指定 slug が benchmark.channels に存在しない
        collector = _make_collector(
            MagicMock(),
            benchmark_channels=[{"id": "UC_A", "name": "A", "slug": "a"}],
        )

        # When / Then: 空辞書を返さず ConfigError
        with pytest.raises(ConfigError, match="unknown"):
            collector.collect_all(competitor_slug="unknown")

    def test_wraps_http_error_from_channels_list(self, no_retry_backoff):
        # Given: channels.list 自体が HttpError
        youtube = MagicMock()
        youtube.channels.return_value.list.return_value.execute.side_effect = _http_error(
            status=429, reason="rateLimitExceeded"
        )
        collector = _make_collector(
            youtube,
            benchmark_channels=[{"id": "UC_A", "name": "A", "slug": "a"}],
        )

        # When / Then: _fetch_channels_metadata 経由でドメイン例外に変換
        with pytest.raises(YouTubeAPIError) as exc:
            collector.collect_all(force=True)
        assert exc.value.status_code == 429


class TestEnsureBenchmarkFresh:
    def test_raises_when_no_channels_configured(self, monkeypatch):
        # Given: benchmark.channels が空
        from youtube_automation.scripts import benchmark_collector as mod

        def _fake_init(self):
            self.config = SimpleNamespace(analytics=SimpleNamespace(benchmark=SimpleNamespace(channels=[])))
            self.youtube = None
            self.benchmark_config = {}
            self.channel_dir = SimpleNamespace()
            self.benchmarks_dir = SimpleNamespace()
            self.data_dir = SimpleNamespace()
            self.today = SimpleNamespace()

        monkeypatch.setattr(mod.BenchmarkCollector, "__init__", _fake_init)

        # When / Then: 黙って return せず ConfigError
        with pytest.raises(ConfigError, match="benchmark.channels"):
            mod.ensure_benchmark_fresh(data_dir=SimpleNamespace())
