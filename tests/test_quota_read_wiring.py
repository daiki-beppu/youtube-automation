"""channel status・stream key・metadata audit・playlist status の read quota 記録配線（Issue #2055）。

各 CLI の read API 呼び出しが、成功・失敗のどちらでも実行された API 試行ごとに
cost_tracker.log_quota を 1 回呼ぶことを固定する。
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
    service = MagicMock()
    channel_resp = {
        "items": [
            {
                "snippet": {"title": "Test Channel"},
                "statistics": {"subscriberCount": "10", "viewCount": "100", "videoCount": "3"},
            }
        ]
    }
    uploads_resp = {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU_test"}}}]}
    service.channels.return_value.list.return_value.execute.side_effect = [channel_resp, uploads_resp]
    service.playlists.return_value.list.return_value.execute.return_value = {
        "items": [{"id": "PL1", "snippet": {"title": "complete collection vol.1"}}]
    }
    service.playlistItems.return_value.list.return_value.execute.return_value = {
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
    analytics = MagicMock()
    analytics.reports.return_value.query.return_value.execute.return_value = {
        "rows": [["vid1", 5, 12.3, 60]]
    }
    collector.youtube_service = get_channel_status_module.YouTubeDataAdapter(
        get_channel_status_module._DeferredService(lambda: service),
        retry_requests=False,
        on_request=lambda bucket: get_channel_status_module._record_read_quota(bucket),
    )
    collector.analytics_service = get_channel_status_module.AnalyticsAdapter(
        analytics,
        retry_requests=False,
        on_request=lambda bucket: get_channel_status_module._record_read_quota(
            bucket, service=get_channel_status_module._ANALYTICS_QUOTA_SERVICE
        ),
    )
    collector._test_service = service
    return collector


class TestGetChannelStatusQuota:
    @pytest.mark.parametrize("failure_stage", ["youtube", "analytics"])
    def test_channel_status_composition_keeps_each_adapter_single_attempt(
        self, failure_stage, monkeypatch
    ):
        """The production composition passes non-retrying adapters to the collector."""
        config = MagicMock()
        config.meta.channel_short = "Test"
        config.analytics.collection_filter_keywords = []
        monkeypatch.setattr(get_channel_status_module, "load_config", lambda: config)
        monkeypatch.setattr(get_channel_status_module, "channel_dir", lambda: MagicMock())

        channel_response = {
            "id": "UC_test",
            "snippet": {"title": "Test Channel"},
            "statistics": {"subscriberCount": "10", "viewCount": "100", "videoCount": "1"},
        }
        channel_api_response = {"items": [channel_response]}
        uploads_response = {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU_test"}}}]}

        youtube_service = MagicMock()
        youtube_service.channels.return_value.list.return_value.execute.side_effect = [
            _http_error("503") if failure_stage == "youtube" else channel_api_response,
            channel_api_response,
            uploads_response,
        ]
        youtube_service.playlists.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "PL1", "snippet": {"title": "complete collection"}}]
        }
        youtube_service.playlistItems.return_value.list.return_value.execute.return_value = {
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

        analytics_service = MagicMock()
        analytics_service.reports.return_value.query.return_value.execute.side_effect = [
            _http_error("503") if failure_stage == "analytics" else {"rows": []}
        ]
        monkeypatch.setattr(get_channel_status_module, "get_youtube_readonly", lambda: youtube_service)
        monkeypatch.setattr(get_channel_status_module, "get_analytics", lambda: analytics_service)
        monkeypatch.setattr(get_channel_status_module, "get_reporting", MagicMock())
        monkeypatch.setattr(get_channel_status_module, "get_credentials_readonly", MagicMock())

        captured = {}
        collector_type = get_channel_status_module.YouTubeAnalyticsCollector

        def build_collector(**kwargs):
            captured.update(kwargs)
            return collector_type(**kwargs)

        monkeypatch.setattr(get_channel_status_module, "YouTubeAnalyticsCollector", build_collector)

        result = get_channel_status_module.get_channel_latest_status()

        assert isinstance(captured["youtube_client"], get_channel_status_module.YouTubeDataAdapter)
        assert isinstance(captured["analytics_client"], get_channel_status_module.AnalyticsAdapter)
        assert captured["youtube_client"]._retry_requests is False
        assert captured["analytics_client"]._retry_requests is False
        if failure_stage == "youtube":
            assert "error" in result
            assert youtube_service.channels.return_value.list.return_value.execute.call_count == 1
        else:
            assert "error" not in result
            assert analytics_service.reports.return_value.query.return_value.execute.call_count == 1

    def test_channel_resolution_records_its_read_request(self, quota_recorder):
        service = MagicMock()
        service.channels.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "UC_test", "snippet": {"title": "Test Channel"}}]
        }

        resolved = get_channel_status_module.YouTubeDataAdapter(
            service,
            retry_requests=True,
            on_request=lambda bucket: get_channel_status_module._record_read_quota(bucket),
        ).resolve_channel()

        assert resolved["id"] == "UC_test"
        assert quota_recorder == [("youtube-data-api", "channels.list", 1)]

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
        collector._test_service.channels.return_value.list.return_value.execute.side_effect = _http_error()
        with patch.object(get_channel_status_module, "YouTubeAnalyticsCollector", return_value=collector):
            status = get_channel_status_module.get_channel_latest_status()

        assert "error" in status
        assert quota_recorder == [
            ("youtube-data-api", "channels.list", 1),
        ]

    def test_missing_channel_returns_error_dict(self, quota_recorder):
        collector = MagicMock()
        collector.initialize.side_effect = YouTubeAPIError("YouTube channel was not found")
        with patch.object(get_channel_status_module, "YouTubeAnalyticsCollector", return_value=collector):
            status = get_channel_status_module.get_channel_latest_status()

        assert status == {"error": "取得エラー: YouTube channel was not found"}

    def test_retry_records_quota_for_each_request_attempt(self, quota_recorder, monkeypatch):
        service = MagicMock()
        service.channels.return_value.list.return_value.execute.side_effect = [
            _http_error(),
            _http_error(),
            {"items": [{"id": "UC_test"}]},
        ]
        monkeypatch.setattr("youtube_automation.utils.retry._DEFAULT_SLEEP", lambda _: None)
        monkeypatch.setattr("youtube_automation.utils.retry._DEFAULT_JITTER", lambda _start, _end: 0)

        resolved = get_channel_status_module.YouTubeDataAdapter(
            service,
            retry_requests=True,
            on_request=lambda bucket: get_channel_status_module._record_read_quota(bucket),
        ).resolve_channel()

        assert resolved == {"id": "UC_test"}
        assert service.channels.return_value.list.return_value.execute.call_count == 3
        assert quota_recorder == [
            ("youtube-data-api", "channels.list", 1),
            ("youtube-data-api", "channels.list", 1),
            ("youtube-data-api", "channels.list", 1),
        ]

    def test_analytics_retry_records_quota_for_each_request_attempt(self, quota_recorder, monkeypatch):
        client = MagicMock()
        client.reports.return_value.query.return_value.execute.side_effect = [
            _http_error(),
            _http_error(),
            {"rows": []},
        ]
        monkeypatch.setattr("youtube_automation.utils.retry._DEFAULT_SLEEP", lambda _: None)
        monkeypatch.setattr("youtube_automation.utils.retry._DEFAULT_JITTER", lambda _start, _end: 0)

        response = get_channel_status_module.AnalyticsAdapter(
            client,
            retry_requests=True,
            on_request=lambda bucket: get_channel_status_module._record_read_quota(
                bucket, service=get_channel_status_module._ANALYTICS_QUOTA_SERVICE
            ),
        ).query(ids="channel==UC_test")

        assert response == {"rows": []}
        assert quota_recorder == [
            ("youtube-analytics-api", "reports.query", 1),
            ("youtube-analytics-api", "reports.query", 1),
            ("youtube-analytics-api", "reports.query", 1),
        ]

    def test_broken_tracker_propagates_unexpected_error(self, broken_tracker):
        collector = _collector_mock()
        with patch.object(get_channel_status_module, "YouTubeAnalyticsCollector", return_value=collector):
            with pytest.raises(RuntimeError, match="tracker unavailable"):
                get_channel_status_module.get_channel_latest_status()

    def test_unexpected_analytics_error_propagates(self, quota_recorder):
        collector = _collector_mock()
        collector.analytics_service._client.reports.return_value.query.return_value.execute.side_effect = RuntimeError(
            "adapter bug"
        )
        with patch.object(get_channel_status_module, "YouTubeAnalyticsCollector", return_value=collector):
            with pytest.raises(RuntimeError, match="adapter bug"):
                get_channel_status_module.get_channel_latest_status()

    def test_expected_analytics_error_keeps_status_without_stats(self, quota_recorder):
        collector = _collector_mock()
        collector.analytics_service._client.reports.return_value.query.return_value.execute.side_effect = (
            YouTubeAPIError("analytics unavailable")
        )
        with patch.object(get_channel_status_module, "YouTubeAnalyticsCollector", return_value=collector):
            status = get_channel_status_module.get_channel_latest_status()

        assert "error" not in status
        assert "stats" not in status["recent_collections"][0]

    def test_unexpected_initialization_error_propagates(self, quota_recorder):
        with patch.object(
            get_channel_status_module,
            "YouTubeAnalyticsCollector",
            side_effect=RuntimeError("collector bug"),
        ):
            with pytest.raises(RuntimeError, match="collector bug"):
                get_channel_status_module.get_channel_latest_status()



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
        with patch("youtube_automation.utils.youtube_service.get_youtube_readonly", return_value=yt):
            issues = metadata_audit_module.audit_remote({"vid1": "col-a"})

        assert issues["vid1"] == ["not found on YouTube"]
        assert quota_recorder == [("youtube-data-api", "videos.list", 1)]

    def test_api_failure_records_quota_and_propagates(self, quota_recorder):
        yt = self._yt({})
        yt.videos.return_value.list.return_value.execute.side_effect = _http_error()
        with patch("youtube_automation.utils.youtube_service.get_youtube_readonly", return_value=yt):
            with pytest.raises(HttpError):
                metadata_audit_module.audit_remote({"vid1": "col-a"})

        assert quota_recorder == [("youtube-data-api", "videos.list", 1)]

    def test_broken_tracker_keeps_result(self, broken_tracker):
        yt = self._yt({"items": []})
        with patch("youtube_automation.utils.youtube_service.get_youtube_readonly", return_value=yt):
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
