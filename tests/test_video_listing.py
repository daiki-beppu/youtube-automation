"""
VideoListingMixin のユニットテスト

テスト対象: utils/video_listing.py

検証観点:
  - get_all_channel_videos のインスタンスキャッシュ（2 回目は API を叩かない）
  - refresh=True でキャッシュを無視して再取得する
  - 空リストはキャッシュしない（2 回目も API を叩く）
  - HttpError は YouTubeAPIError に変換して re-raise する（握りつぶさない）
  - get_recent_videos の直近フィルタが UTC aware 比較になっている（TZ 境界ズレなし）
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from youtube_automation.utils.exceptions import YouTubeAPIError
from youtube_automation.utils.video_listing import VideoListingMixin


def _make_http_error(status: int = 403, message: bytes = b"error") -> HttpError:
    """指定ステータスの HttpError を生成する。"""
    resp = Response({"status": status})
    return HttpError(resp, message)


class _FakeExecutable:
    """`.execute()` を呼ぶと事前に登録した値を返す（または例外を投げる）フェイク"""

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._result


class _FakePlaylistItems:
    """playlistItems().list(...).execute() の呼び出し回数を記録するフェイク"""

    def __init__(self, pages: List[Dict] | None = None, error: Exception | None = None) -> None:
        self._pages = pages or []
        self._error = error
        self.call_count = 0

    def list(self, **kwargs):
        self.call_count += 1
        if self._error is not None:
            return _FakeExecutable(error=self._error)
        # pageToken に応じたページを返す（単純化のため 1 ページのみ想定 or index 対応）
        page_token = kwargs.get("pageToken")
        index = 0 if page_token is None else int(page_token)
        page = self._pages[index]
        return _FakeExecutable(result=page)


class _FakeChannels:
    def list(self, **kwargs):
        return _FakeExecutable(result={"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UP_PLAYLIST"}}}]})


class _FakeYouTubeService:
    def __init__(self, playlist_items: _FakePlaylistItems) -> None:
        self._playlist_items = playlist_items

    def channels(self):
        return _FakeChannels()

    def playlistItems(self):
        return self._playlist_items


def _video_item(video_id: str, published_at: str) -> Dict:
    return {
        "contentDetails": {"videoId": video_id},
        "snippet": {
            "title": f"title-{video_id}",
            "publishedAt": published_at,
            "description": "desc",
        },
    }


class _StubCollector(VideoListingMixin):
    """VideoListingMixin 検証用のスタブコレクター"""

    def __init__(self, playlist_items: _FakePlaylistItems) -> None:
        self.youtube_service = _FakeYouTubeService(playlist_items)
        self.channel_id = "UC_TEST"

    def initialize(self) -> None:  # pragma: no cover - youtube_service は常に注入済み
        pass


class TestGetAllChannelVideosCache:
    def test_second_call_uses_cache(self) -> None:
        playlist_items = _FakePlaylistItems(pages=[{"items": [_video_item("V1", "2026-01-01T00:00:00Z")]}])
        collector = _StubCollector(playlist_items)

        first = collector.get_all_channel_videos()
        second = collector.get_all_channel_videos()

        assert first == second
        assert playlist_items.call_count == 1

    def test_refresh_true_bypasses_cache(self) -> None:
        playlist_items = _FakePlaylistItems(pages=[{"items": [_video_item("V1", "2026-01-01T00:00:00Z")]}])
        collector = _StubCollector(playlist_items)

        collector.get_all_channel_videos()
        collector.get_all_channel_videos(refresh=True)

        assert playlist_items.call_count == 2

    def test_empty_result_is_not_cached(self) -> None:
        playlist_items = _FakePlaylistItems(pages=[{"items": []}])
        collector = _StubCollector(playlist_items)

        first = collector.get_all_channel_videos()
        second = collector.get_all_channel_videos()

        assert first == []
        assert second == []
        assert playlist_items.call_count == 2


class TestGetAllChannelVideosErrors:
    def test_http_error_raises_youtube_api_error(self) -> None:
        playlist_items = _FakePlaylistItems(error=_make_http_error(403))
        collector = _StubCollector(playlist_items)

        with pytest.raises(YouTubeAPIError):
            collector.get_all_channel_videos()


class TestGetRecentVideosTimezoneBoundary:
    def test_video_published_within_utc_boundary_is_included(self) -> None:
        # cutoff の 4 時間後（UTC）に公開された動画。
        # 修正前は naive JST cutoff と比較していたため、この動画は
        # cutoff から 9 時間以内の投稿が誤って漏れる可能性があった。
        days = 7
        published_at = (datetime.now(timezone.utc) - timedelta(days=days) + timedelta(hours=4)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        playlist_items = _FakePlaylistItems(pages=[{"items": [_video_item("V1", published_at)]}])
        collector = _StubCollector(playlist_items)

        recent = collector.get_recent_videos(days=days)

        assert [v["video_id"] for v in recent] == ["V1"]
