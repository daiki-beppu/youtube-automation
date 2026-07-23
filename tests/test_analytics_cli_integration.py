"""yt-analytics の subscribedStatus 収集に関する実経路テスト。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from youtube_automation import cli_entrypoints


class _Request:
    def __init__(self, response: dict | None = None, error: HttpError | None = None) -> None:
        self.response = response or {}
        self.error = error

    def execute(self) -> dict:
        if self.error is not None:
            raise self.error
        return self.response


class _AnalyticsReports:
    def __init__(self, subscribed_status_error: HttpError | None = None) -> None:
        self.subscribed_status_error = subscribed_status_error
        self.queries: list[dict] = []

    def query(self, **kwargs: str | int) -> _Request:
        self.queries.append(kwargs)
        dimensions = kwargs.get("dimensions")
        metrics = kwargs["metrics"]
        if dimensions == "subscribedStatus":
            return _Request(
                response={"rows": [["SUBSCRIBED", 30, 120, 240], ["UNSUBSCRIBED", 70, 280, 180]]},
                error=self.subscribed_status_error,
            )
        if dimensions == "video,day":
            return _Request({"rows": [["VIDEO_1", "2026-04-01", 100]]})
        if dimensions == "video":
            if "estimatedRevenue" in metrics:
                return _Request({"rows": [["VIDEO_1", 100, 2.5, 80, 4.0, 5.0]]})
            if metrics.startswith("views,estimatedMinutesWatched"):
                return _Request({"rows": [["VIDEO_1", 100, 500, 120, 5, 0, 1, 2, 4]]})
            return _Request({"rows": [["VIDEO_1", 100, 5, 1, 500]]})
        if dimensions == "insightTrafficSourceType":
            return _Request({"rows": [["YT_SEARCH", 100, 500, 120]]})
        if dimensions == "deviceType":
            return _Request({"rows": [["MOBILE", 100, 500, 120]]})
        if dimensions == "day" and metrics.startswith("views,estimatedMinutesWatched,averageViewDuration"):
            return _Request({"rows": [["2026-04-01", 100, 500, 120, 4, 0, 5, 0, 1, 2, 50, 0, 0, 0]]})
        if dimensions == "day" and "estimatedRevenue" in metrics:
            return _Request({"rows": [["2026-04-01", 100, 2.5, 80, 4.0, 5.0]]})
        if dimensions == "day":
            return _Request({"rows": [["2026-04-01", 100, 500]]})
        return _Request({"rows": [[100, 5, 1, 2, 4]]})


class _AnalyticsService:
    def __init__(self, reports: _AnalyticsReports) -> None:
        self._reports = reports

    def query(self, **kwargs: str | int) -> dict:
        return self._reports.query(**kwargs).execute()


class _YouTubeService:
    def resolve_channel(self) -> dict:
        return self.channels().list(part="id,snippet,statistics", mine=True).execute()["items"][0]

    def list_uploads(self, channel_id: str) -> dict:
        return {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UPLOADS"}}}]}

    def list_playlist_items(self, playlist_id: str, page_token: str | None) -> dict:
        return self.playlistItems().list(playlistId=playlist_id).execute()

    def list_playlists(self, channel_id: str) -> dict:
        return {"items": []}

    def list_playlist_items_for_display(self, playlist_id: str, *, max_results: int) -> dict:
        return self.list_playlist_items(playlist_id, None)

    def list_videos(self, video_ids: str, *, part: str) -> dict:
        return self.videos().list(id=video_ids, part=part).execute()

    def channels(self) -> MagicMock:
        return MagicMock(
            list=MagicMock(
                return_value=_Request(
                    {
                        "items": [
                            {
                                "id": "UC_TEST",
                                "snippet": {"title": "Test Channel"},
                                "contentDetails": {"relatedPlaylists": {"uploads": "UPLOADS"}},
                            }
                        ]
                    }
                )
            )
        )

    def playlistItems(self) -> MagicMock:
        return MagicMock(
            list=MagicMock(
                return_value=_Request(
                    {
                        "items": [
                            {
                                "contentDetails": {"videoId": "VIDEO_1"},
                                "snippet": {
                                    "title": "Test video",
                                    "publishedAt": "2020-01-01T00:00:00Z",
                                    "description": "description",
                                },
                            }
                        ]
                    }
                )
            )
        )

    def videos(self) -> MagicMock:
        return MagicMock(
            list=MagicMock(
                return_value=_Request(
                    {
                        "items": [
                            {
                                "id": "VIDEO_1",
                                "snippet": {
                                    "title": "Test video",
                                    "publishedAt": "2020-01-01T00:00:00Z",
                                    "description": "description",
                                },
                                "contentDetails": {"duration": "PT2M", "definition": "hd"},
                            }
                        ]
                    }
                )
            )
        )


@pytest.fixture
def cli_dependencies(tmp_path: Path):
    reports = _AnalyticsReports()
    config = MagicMock()
    config.meta.channel_name = "Test Channel"
    config.meta.channel_short = "TC"
    oauth_module = MagicMock()
    oauth_module.YouTubeOAuthHandler.return_value.test_connection.return_value = True

    def initialize(collector) -> None:
        collector.analytics_service = _AnalyticsService(reports)
        collector.youtube_service = _YouTubeService()
        collector.channel_id = "UC_TEST"

    with patch("youtube_automation.scripts.analytics_system.load_config", return_value=config):
        with patch("youtube_automation.scripts.analytics_system.channel_dir", return_value=tmp_path):
            with patch(
                "youtube_automation.domains.analytics.service.YouTubeAnalyticsCollector.initialize",
                new=initialize,
            ):
                with patch.dict(
                    sys.modules,
                    {
                        "youtube_automation.auth": MagicMock(),
                        "youtube_automation.auth.oauth_handler": oauth_module,
                    },
                ):
                    yield tmp_path, reports


def test_yt_analytics_collects_and_saves_subscribed_status_via_cli(cli_dependencies) -> None:
    """CLI 引数から実 collector を通り subscribedStatus を JSON へ保存する。"""
    tmp_path, reports = cli_dependencies

    with patch.object(sys, "argv", ["yt-analytics", "--days", "7"]):
        with pytest.raises(SystemExit) as exited:
            cli_entrypoints.yt_analytics()

    assert exited.value.code == 0
    saved_files = list((tmp_path / "data").glob("analytics_data_*.json"))
    assert len(saved_files) == 1
    payload = json.loads(saved_files[0].read_text(encoding="utf-8"))
    assert payload["audience"]["by_subscribed_status"] == {
        "statuses": {
            "SUBSCRIBED": {
                "views": 30,
                "watch_time_minutes": 120,
                "avg_view_duration": 240,
                "view_share_percent": 30.0,
            },
            "UNSUBSCRIBED": {
                "views": 70,
                "watch_time_minutes": 280,
                "avg_view_duration": 180,
                "view_share_percent": 70.0,
            },
        },
        "total_views": 100,
    }
    assert any(query.get("dimensions") == "subscribedStatus" for query in reports.queries)


def test_yt_analytics_returns_failure_when_subscribed_status_collection_fails(cli_dependencies) -> None:
    """必須 subscribedStatus の API 失敗は CLI の成功終了を許さない。"""
    tmp_path, reports = cli_dependencies
    reports.subscribed_status_error = HttpError(MagicMock(status=500), b"backendError")

    with patch.object(sys, "argv", ["yt-analytics", "--days", "7"]):
        with pytest.raises(SystemExit) as exited:
            cli_entrypoints.yt_analytics()

    assert exited.value.code == 1
    assert not list((tmp_path / "data").glob("analytics_data_*.json"))
