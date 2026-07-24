"""benchmark read API の quota 記録配線（Issue #2056）のユニットテスト

検証対象:
- `BenchmarkCollector` の channels / playlistItems / videos / playlists の各 request 単位で
  `log_quota` が呼ばれる（operation・units・件数が決定的に一致する）
- 複数 page / 複数バッチのとき page request 数と記録件数が一致する
- request が失敗しても quota 記録後に元例外（`YouTubeAPIError`）が伝播する
- tracker が記録できない（`log_quota` が `None` を返す）ときも benchmark 出力は従来通り
- `fetch_benchmark_comments` の `commentThreads.list` も同様に配線される

ネットワークも YouTube API も呼ばない（MagicMock + monkeypatch で差し込み）。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from youtube_automation.infrastructure.errors import YouTubeAPIError
from youtube_automation.scripts.benchmark_collector import (
    _CHANNELS_BATCH_SIZE,
    _QUOTA_SERVICE,
    _READ_QUOTA_UNITS,
    BenchmarkCollector,
)
from youtube_automation.scripts.fetch_benchmark_comments import BenchmarkCommentCollector


@pytest.fixture
def quota_calls(monkeypatch) -> list[dict]:
    """両 script の `log_quota` 呼び出しを捕捉する（ファイル書き込みはしない）。"""
    calls: list[dict] = []

    def _capture(service, bucket, units, *, metadata=None):
        calls.append({"service": service, "bucket": bucket, "units": units, "metadata": dict(metadata or {})})
        return calls[-1]

    monkeypatch.setattr("youtube_automation.scripts.benchmark_collector.log_quota", _capture)
    monkeypatch.setattr("youtube_automation.scripts.fetch_benchmark_comments.log_quota", _capture)
    return calls


def _make_collector(youtube_mock: MagicMock) -> BenchmarkCollector:
    collector = BenchmarkCollector()
    collector.youtube = youtube_mock
    return collector


def _ch_item(channel_id: str, *, uploads: str = "UU_DUMMY") -> dict:
    return {
        "id": channel_id,
        "snippet": {"title": channel_id},
        "statistics": {"subscriberCount": "1000", "videoCount": "10"},
        "contentDetails": {"relatedPlaylists": {"uploads": uploads}},
    }


def _video_item(video_id: str) -> dict:
    return {
        "id": video_id,
        "snippet": {
            "title": f"video {video_id}",
            "publishedAt": "2026-05-01T12:00:00Z",
            "description": "",
            "tags": [],
            "thumbnails": {"high": {"url": f"https://example.com/{video_id}.jpg"}},
        },
        "statistics": {"viewCount": "20000", "likeCount": "100", "commentCount": "5"},
        "contentDetails": {"duration": "PT1H"},
    }


def _buckets(calls: list[dict]) -> list[str]:
    return [c["bucket"] for c in calls]


class TestBenchmarkCollectorQuotaWiring:
    def test_fetch_channels_metadata_records_one_entry_per_batch_request(self, quota_calls):
        # Given: バッチ上限 + 5 件 = channels.list 2 request
        n = _CHANNELS_BATCH_SIZE + 5
        channel_infos = [{"id": f"UC_{i}"} for i in range(n)]
        youtube = MagicMock()

        def _list(**kwargs):
            ids = kwargs["id"].split(",")
            mock_request = MagicMock()
            mock_request.execute.return_value = {"items": [_ch_item(cid) for cid in ids]}
            return mock_request

        youtube.channels.return_value.list.side_effect = _list
        collector = _make_collector(youtube)

        # When
        collector._fetch_channels_metadata(channel_infos)

        # Then: request 数 = 記録件数、operation / units も一致
        assert _buckets(quota_calls) == ["channels.list", "channels.list"]
        assert all(c["service"] == _QUOTA_SERVICE for c in quota_calls)
        assert all(c["units"] == _READ_QUOTA_UNITS for c in quota_calls)
        assert [c["metadata"]["batch_size"] for c in quota_calls] == [_CHANNELS_BATCH_SIZE, 5]

    def test_collect_channel_records_quota_per_page_and_batch(self, quota_calls):
        # Given: playlistItems 2 page（50 + 30 件）→ videos.list 2 バッチ（50 + 30 件）
        youtube = MagicMock()
        page1_ids = [f"VID_{i}" for i in range(50)]
        page2_ids = [f"VID_{i}" for i in range(50, 80)]
        playlist_responses = [
            {"items": [{"contentDetails": {"videoId": v}} for v in page1_ids], "nextPageToken": "P2"},
            {"items": [{"contentDetails": {"videoId": v}} for v in page2_ids]},
        ]
        youtube.playlistItems.return_value.list.return_value.execute.side_effect = playlist_responses

        def _videos_list(**kwargs):
            ids = kwargs["id"].split(",")
            mock_request = MagicMock()
            mock_request.execute.return_value = {"items": [_video_item(v) for v in ids]}
            return mock_request

        youtube.videos.return_value.list.side_effect = _videos_list
        collector = _make_collector(youtube)
        collector.benchmark_config = {"scan_recent": 80, "min_views": 10000}

        # When
        result = collector.collect_channel({"id": "UC_OK", "name": "ok", "slug": "ok"}, _ch_item("UC_OK"))

        # Then: page request 数と記録件数が一致する
        assert _buckets(quota_calls) == [
            "playlistItems.list",
            "playlistItems.list",
            "videos.list",
            "videos.list",
        ]
        assert all(c["service"] == _QUOTA_SERVICE for c in quota_calls)
        assert all(c["units"] == _READ_QUOTA_UNITS for c in quota_calls)
        assert result["scanned_count"] == 80

    def test_collect_playlists_records_quota_for_all_three_stages(self, quota_calls):
        # Given: playlists.list 2 page（各 1 playlist）→ 各 playlist の playlistItems 1 page
        #        → videos.list 1 バッチ
        youtube = MagicMock()
        youtube.playlists.return_value.list.return_value.execute.side_effect = [
            {
                "items": [
                    {"id": "PL_1", "snippet": {"title": "p1"}, "contentDetails": {"itemCount": 1}},
                ],
                "nextPageToken": "P2",
            },
            {
                "items": [
                    {"id": "PL_2", "snippet": {"title": "p2"}, "contentDetails": {"itemCount": 1}},
                ],
            },
        ]
        youtube.playlistItems.return_value.list.return_value.execute.side_effect = [
            {"items": [{"snippet": {"position": 0}, "contentDetails": {"videoId": "VID_A"}}]},
            {"items": [{"snippet": {"position": 0}, "contentDetails": {"videoId": "VID_B"}}]},
        ]
        youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": [_video_item("VID_A"), _video_item("VID_B")],
        }
        collector = _make_collector(youtube)

        # When
        result = collector.collect_playlists({"id": "UC_OK", "name": "ok", "slug": "ok"})

        # Then: playlists 2 + playlistItems 2 + videos 1 = 5 件
        assert _buckets(quota_calls) == [
            "playlists.list",
            "playlists.list",
            "playlistItems.list",
            "playlistItems.list",
            "videos.list",
        ]
        assert all(c["units"] == _READ_QUOTA_UNITS for c in quota_calls)
        assert len(result["playlists"]) == 2

    def test_failed_request_records_quota_then_propagates_original_exception(self, quota_calls):
        # Given: channels.list が非 retryable な 400 で失敗する
        youtube = MagicMock()
        error = HttpError(Response({"status": "400"}), b'{"error": {"errors": [{"reason": "badRequest"}]}}')
        youtube.channels.return_value.list.return_value.execute.side_effect = error
        collector = _make_collector(youtube)

        # When / Then: quota 記録後も元例外（ドメイン変換済み）が維持される
        with pytest.raises(YouTubeAPIError):
            collector._fetch_channels_metadata([{"id": "UC_FAIL"}])

        assert _buckets(quota_calls) == ["channels.list"]

    def test_output_unchanged_when_tracker_cannot_record(self, monkeypatch):
        # Given: tracker が記録できない（書き込み失敗時と同じく None を返す）
        monkeypatch.setattr(
            "youtube_automation.scripts.benchmark_collector.log_quota",
            lambda *args, **kwargs: None,
        )
        youtube = MagicMock()
        youtube.playlistItems.return_value.list.return_value.execute.return_value = {
            "items": [{"contentDetails": {"videoId": "VID_1"}}],
            "nextPageToken": None,
        }
        youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": [_video_item("VID_1")],
        }
        collector = _make_collector(youtube)
        collector.benchmark_config = {"scan_recent": 1, "min_views": 10000}

        # When
        result = collector.collect_channel({"id": "UC_OK", "name": "ok", "slug": "ok"}, _ch_item("UC_OK"))

        # Then: benchmark JSON 相当の出力は従来通り（quota 由来のキーも混入しない）
        assert result["channel_id"] == "UC_OK"
        assert result["scanned_count"] == 1
        assert [v["video_id"] for v in result["videos"]] == ["VID_1"]
        assert "quota" not in result


class TestFetchBenchmarkCommentsQuotaWiring:
    def _make_comment_collector(self, youtube_mock: MagicMock) -> BenchmarkCommentCollector:
        collector = BenchmarkCommentCollector()
        collector.youtube = youtube_mock
        return collector

    def test_fetch_comments_records_one_entry_per_request(self, quota_calls):
        # Given: commentThreads.list が 1 件返す
        youtube = MagicMock()
        youtube.commentThreads.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "id": "C1",
                            "snippet": {
                                "authorDisplayName": "a",
                                "textOriginal": "great",
                                "likeCount": 3,
                                "publishedAt": "2026-05-01T00:00:00Z",
                            },
                        }
                    }
                }
            ],
        }
        collector = self._make_comment_collector(youtube)

        # When
        comments = collector._fetch_comments("VID_C")

        # Then
        assert len(comments) == 1
        assert _buckets(quota_calls) == ["commentThreads.list"]
        assert quota_calls[0]["service"] == _QUOTA_SERVICE
        assert quota_calls[0]["units"] == _READ_QUOTA_UNITS
        assert quota_calls[0]["metadata"]["video_id"] == "VID_C"

    def test_fetch_comments_failure_records_quota_and_keeps_original_handling(self, quota_calls, caplog):
        # Given: commentThreads.list が失敗する（コメント無効化等）
        youtube = MagicMock()
        youtube.commentThreads.return_value.list.return_value.execute.side_effect = RuntimeError("commentsDisabled")
        collector = self._make_comment_collector(youtube)

        # When: 既存挙動（warn + 空リスト）は維持され、quota は記録される
        with caplog.at_level("WARNING"):
            comments = collector._fetch_comments("VID_FAIL")

        # Then: 元例外がそのまま警告ログに現れ、記録件数は request 数と一致する
        assert comments == []
        assert _buckets(quota_calls) == ["commentThreads.list"]
        assert quota_calls[0]["metadata"]["video_id"] == "VID_FAIL"
        assert "commentsDisabled" in caplog.text
