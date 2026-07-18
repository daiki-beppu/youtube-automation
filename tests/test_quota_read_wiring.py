"""channel status・stream key・metadata audit・playlist status の read quota 記録配線（Issue #2055）。

各 CLI の read API 呼び出しが、成功・失敗のどちらでもリクエスト 1 回につき
cost_tracker.log_quota を 1 回だけ呼ぶことを固定する。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httplib2
import pytest
from googleapiclient.errors import HttpError

import youtube_automation.scripts.fetch_stream_key as fetch_stream_key_module
import youtube_automation.scripts.get_channel_status as get_channel_status_module
import youtube_automation.scripts.metadata_audit as metadata_audit_module
import youtube_automation.scripts.playlist_status as playlist_status_module
from youtube_automation.utils import cost_tracker
from youtube_automation.utils.exceptions import YouTubeAPIError


@pytest.fixture
def quota_recorder(monkeypatch):
    """log_quota をインメモリ記録に差し替え、(service, bucket, units) を収集する。"""
    records: list[tuple[str, str, float]] = []

    def fake_log_quota(service, bucket, units, *, metadata=None):
        records.append((service, bucket, units))
        return {"service": service, "bucket": bucket, "units": units}

    monkeypatch.setattr(cost_tracker, "log_quota", fake_log_quota)
    return records


@pytest.fixture
def broken_tracker(monkeypatch):
    """tracker 無効時（log_quota が例外を吐く）をシミュレートする。"""

    def raise_log_quota(*args, **kwargs):
        raise RuntimeError("tracker unavailable")

    monkeypatch.setattr(cost_tracker, "log_quota", raise_log_quota)


def _http_error(status: str = "500") -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b"boom")


# ============================================================
# get_channel_status
# ============================================================


def _collector_mock() -> MagicMock:
    collector = MagicMock()
    collector.channel_id = "UC_test"
    channel_resp = {
        "items": [
            {
                "snippet": {"title": "Test Channel"},
                "statistics": {"subscriberCount": "10", "viewCount": "100", "videoCount": "3"},
            }
        ]
    }
    uploads_resp = {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU_test"}}}]}
    collector.youtube_service.channels.return_value.list.return_value.execute.side_effect = [
        channel_resp,
        uploads_resp,
    ]
    collector.youtube_service.playlists.return_value.list.return_value.execute.return_value = {
        "items": [{"id": "PL1", "snippet": {"title": "complete collection vol.1"}}]
    }
    collector.youtube_service.playlistItems.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "snippet": {
                    "title": "Video A",
                    "publishedAt": "2026-07-01T00:00:00Z",
                    "resourceId": {"videoId": "vid1"},
                }
            }
        ]
    }
    collector.analytics_service.reports.return_value.query.return_value.execute.return_value = {
        "rows": [["vid1", 5, 12.3, 60]]
    }
    return collector


class TestGetChannelStatusQuota:
    def test_success_records_each_read_request_once(self, quota_recorder):
        collector = _collector_mock()
        with patch.object(get_channel_status_module, "YouTubeAnalyticsCollector", return_value=collector):
            status = get_channel_status_module.get_channel_latest_status()

        assert "error" not in status
        assert quota_recorder == [
            ("youtube-data-api", "channels.list", 1),
            ("youtube-data-api", "channels.list", 1),
            ("youtube-data-api", "playlists.list", 1),
            ("youtube-data-api", "playlistItems.list", 1),
            ("youtube-analytics-api", "reports.query", 1),
        ]

    def test_api_failure_still_records_consumed_quota(self, quota_recorder):
        collector = _collector_mock()
        collector.youtube_service.channels.return_value.list.return_value.execute.side_effect = _http_error()
        with patch.object(get_channel_status_module, "YouTubeAnalyticsCollector", return_value=collector):
            status = get_channel_status_module.get_channel_latest_status()

        assert "error" in status
        assert quota_recorder == [("youtube-data-api", "channels.list", 1)]

    def test_broken_tracker_keeps_output_and_result(self, broken_tracker):
        collector = _collector_mock()
        with patch.object(get_channel_status_module, "YouTubeAnalyticsCollector", return_value=collector):
            status = get_channel_status_module.get_channel_latest_status()

        assert "error" not in status
        assert status["channel_name"] == "Test Channel"


# ============================================================
# fetch_stream_key
# ============================================================


class TestFetchStreamKeyQuota:
    def _service(self) -> MagicMock:
        service = MagicMock()
        service.liveStreams.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "s1", "snippet": {"title": "Default Stream Key"}}]
        }
        return service

    def test_success_records_livestreams_list_once(self, quota_recorder):
        with patch.object(fetch_stream_key_module, "build", return_value=self._service()):
            streams = fetch_stream_key_module.list_live_streams(credentials=MagicMock())

        assert len(streams) == 1
        assert quota_recorder == [("youtube-data-api", "liveStreams.list", 1)]

    def test_api_failure_records_quota_and_raises_domain_error(self, quota_recorder):
        service = self._service()
        service.liveStreams.return_value.list.return_value.execute.side_effect = _http_error("403")
        with patch.object(fetch_stream_key_module, "build", return_value=service):
            with pytest.raises(YouTubeAPIError):
                fetch_stream_key_module.list_live_streams(credentials=MagicMock())

        assert quota_recorder == [("youtube-data-api", "liveStreams.list", 1)]

    def test_broken_tracker_keeps_result(self, broken_tracker):
        with patch.object(fetch_stream_key_module, "build", return_value=self._service()):
            streams = fetch_stream_key_module.list_live_streams(credentials=MagicMock())

        assert len(streams) == 1


# ============================================================
# metadata_audit
# ============================================================


class TestMetadataAuditQuota:
    def _yt(self, response: dict) -> MagicMock:
        yt = MagicMock()
        yt.videos.return_value.list.return_value.execute.return_value = response
        return yt

    def test_success_records_videos_list_once(self, quota_recorder):
        yt = self._yt({"items": []})
        with patch("youtube_automation.utils.youtube_service.get_youtube", return_value=yt):
            issues = metadata_audit_module.audit_remote({"vid1": "col-a"})

        assert issues["vid1"] == ["not found on YouTube"]
        assert quota_recorder == [("youtube-data-api", "videos.list", 1)]

    def test_api_failure_records_quota_and_propagates(self, quota_recorder):
        yt = self._yt({})
        yt.videos.return_value.list.return_value.execute.side_effect = _http_error()
        with patch("youtube_automation.utils.youtube_service.get_youtube", return_value=yt):
            with pytest.raises(HttpError):
                metadata_audit_module.audit_remote({"vid1": "col-a"})

        assert quota_recorder == [("youtube-data-api", "videos.list", 1)]

    def test_broken_tracker_keeps_result(self, broken_tracker):
        yt = self._yt({"items": []})
        with patch("youtube_automation.utils.youtube_service.get_youtube", return_value=yt):
            issues = metadata_audit_module.audit_remote({"vid1": "col-a"})

        assert issues["vid1"] == ["not found on YouTube"]


# ============================================================
# playlist_status
# ============================================================


def _viewer_with_youtube(youtube: MagicMock) -> playlist_status_module.PlaylistStatusViewer:
    viewer = object.__new__(playlist_status_module.PlaylistStatusViewer)
    viewer._youtube = youtube
    return viewer


class TestPlaylistStatusQuota:
    def test_pagination_records_one_entry_per_request(self, quota_recorder):
        youtube = MagicMock()
        req1, req2 = MagicMock(), MagicMock()
        req1.execute.return_value = {"items": [{"contentDetails": {"videoId": "v1"}}]}
        req2.execute.return_value = {"items": [{"contentDetails": {"videoId": "v2"}}]}
        youtube.playlistItems.return_value.list.return_value = req1
        youtube.playlistItems.return_value.list_next.side_effect = [req2, None]

        viewer = _viewer_with_youtube(youtube)
        video_ids = viewer._list_playlist_video_ids("PL1")

        assert video_ids == {"v1", "v2"}
        assert quota_recorder == [
            ("youtube-data-api", "playlistItems.list", 1),
            ("youtube-data-api", "playlistItems.list", 1),
        ]

    def test_api_failure_records_consumed_quota(self, quota_recorder):
        youtube = MagicMock()
        req = MagicMock()
        req.execute.side_effect = _http_error()
        youtube.playlistItems.return_value.list.return_value = req

        viewer = _viewer_with_youtube(youtube)
        video_ids = viewer._list_playlist_video_ids("PL1")

        # 既存挙動: 取得エラーは警告して空セットを返す（終了状態は変えない）
        assert video_ids == set()
        assert quota_recorder == [("youtube-data-api", "playlistItems.list", 1)]

    def test_broken_tracker_keeps_result(self, broken_tracker):
        youtube = MagicMock()
        req = MagicMock()
        req.execute.return_value = {"items": [{"contentDetails": {"videoId": "v1"}}]}
        youtube.playlistItems.return_value.list.return_value = req
        youtube.playlistItems.return_value.list_next.return_value = None

        viewer = _viewer_with_youtube(youtube)
        assert viewer._list_playlist_video_ids("PL1") == {"v1"}
