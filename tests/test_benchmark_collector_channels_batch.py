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

from types import SimpleNamespace
from unittest.mock import MagicMock

from youtube_automation.scripts.benchmark_collector import (
    _CHANNELS_BATCH_SIZE,
    BenchmarkCollector,
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


class TestFetchChannelsMetadata:
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
    def test_returns_empty_dict_when_ch_item_is_empty(self):
        # Given: 上位で API レスポンスに含まれていなかったケースを模倣
        youtube = MagicMock()
        collector = _make_collector(youtube)

        # When
        result = collector.collect_channel({"id": "UC_X", "name": "x", "slug": "x"}, {})

        # Then: 空辞書 + channels.list を再呼び出ししない（プリフェッチ済みの契約）
        assert result == {}
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

    def test_collect_all_skips_channels_missing_from_api(self):
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

        # When
        data = collector.collect_all(force=True)

        # Then: 削除済みは結果に含まれず、生存分のみ返る
        assert [c["channel_id"] for c in data["channels"]] == ["UC_OK"]
