"""Channel status CLI output and failure contracts."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from youtube_automation.commands.channel import channel_status


def _status() -> dict:
    return {
        "channel_name": "Reference Channel",
        "subscriber_count": 1234,
        "total_views": 56789,
        "video_count": 12,
        "updated_at": "2026-07-30 12:34:56",
        "recent_collections": [
            {
                "collection_name": "Collection A",
                "published_at": "2026-07-29",
                "video_id": "video-a",
                "stats": {
                    "views": 1000,
                    "watch_time_min": 2500,
                    "avg_view_duration_sec": 180,
                },
            },
            {
                "collection_name": "Collection B",
                "published_at": "2026-07-20",
                "video_id": "video-b",
            },
        ],
        "collections_count": 2,
        "estimated_tracks": 10,
    }


def test_main_json_outputs_complete_status_without_display_config(monkeypatch, capsys):
    status = _status()
    load_config = MagicMock(side_effect=AssertionError("JSON mode must not load display config"))
    monkeypatch.setattr(channel_status, "get_channel_latest_status", lambda: status)
    monkeypatch.setattr(channel_status, "load_config", load_config)
    monkeypatch.setattr(sys, "argv", ["yt-channel-status", "--json"])

    channel_status.main()

    assert json.loads(capsys.readouterr().out) == status
    load_config.assert_not_called()


def test_main_summary_outputs_aggregates_without_display_config(monkeypatch, capsys):
    load_config = MagicMock(side_effect=AssertionError("summary mode must not load display config"))
    monkeypatch.setattr(channel_status, "get_channel_latest_status", _status)
    monkeypatch.setattr(channel_status, "load_config", load_config)
    monkeypatch.setattr(sys, "argv", ["yt-channel-status", "--summary"])

    channel_status.main()

    assert capsys.readouterr().out.splitlines() == [
        "チャンネル: Reference Channel",
        "登録者: 1,234人",
        "総動画数: 12本",
        "コレクション: 2個",
        "推定トラック数: 10曲",
    ]
    load_config.assert_not_called()


def test_main_detail_outputs_channel_and_collection_statistics(monkeypatch, capsys):
    monkeypatch.setattr(channel_status, "get_channel_latest_status", _status)
    monkeypatch.setattr(
        channel_status,
        "load_config",
        lambda: SimpleNamespace(meta=SimpleNamespace(channel_name="Display Name", channel_short="REF")),
    )
    monkeypatch.setattr(sys, "argv", ["yt-channel-status"])

    channel_status.main()

    output = capsys.readouterr().out
    assert "Display Name (REF) - 最新状況" in output
    assert "Reference Channel" in output
    assert "1,234人" in output
    assert "56,789回" in output
    assert "Collection A (2026-07-29)" in output
    assert "1,000 views" in output
    assert "avg 3.0min/view" in output
    assert "Collection B (2026-07-20)" in output


def test_main_error_prints_message_and_exits_one(monkeypatch, capsys):
    monkeypatch.setattr(
        channel_status,
        "get_channel_latest_status",
        lambda: {"error": "取得エラー: unavailable"},
    )
    monkeypatch.setattr(sys, "argv", ["yt-channel-status", "--json"])

    with pytest.raises(SystemExit) as error:
        channel_status.main()

    assert error.value.code == 1
    assert capsys.readouterr().out == "❌ 取得エラー: unavailable\n"


def test_get_status_falls_back_to_uploads_when_collection_playlists_are_empty(monkeypatch):
    config = SimpleNamespace(
        meta=SimpleNamespace(channel_short="ref"),
        analytics=SimpleNamespace(collection_filter_keywords=("Complete", "Collection")),
    )
    monkeypatch.setattr(channel_status, "load_config", lambda: config)
    monkeypatch.setattr(channel_status, "channel_dir", lambda: MagicMock())
    monkeypatch.setattr(
        channel_status,
        "create_readonly_youtube_clients",
        lambda: SimpleNamespace(
            youtube_readonly=MagicMock(),
            analytics=MagicMock(),
            reporting=MagicMock(),
            credentials_readonly=MagicMock(),
        ),
    )
    collector = MagicMock()
    collector.channel_id = "UC_REF"
    collector.youtube_service.resolve_channel.return_value = {
        "snippet": {"title": "Reference Channel"},
        "statistics": {"subscriberCount": "10", "viewCount": "20", "videoCount": "1"},
    }
    collector.youtube_service.list_uploads.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU_REF"}}}]
    }
    collector.youtube_service.list_playlists.return_value = {"items": []}
    collector.youtube_service.list_playlist_items_for_display.return_value = {
        "items": [
            {
                "snippet": {
                    "title": "Fallback upload",
                    "publishedAt": "2026-07-30T00:00:00Z",
                    "resourceId": {"videoId": "video-fallback"},
                }
            }
        ]
    }
    collector.analytics_service.query.return_value = {"rows": [["video-fallback", 321, 42.5, 100]]}
    monkeypatch.setattr(channel_status, "YouTubeAnalyticsCollector", MagicMock(return_value=collector))

    result = channel_status.get_channel_latest_status()

    query = collector.analytics_service.query.call_args.kwargs
    assert query["metrics"] == "engagedViews,estimatedMinutesWatched,averageViewDuration"
    assert query["sort"] == "-engagedViews"
    assert result["recent_collections"] == [
        {
            "collection_name": "Fallback upload",
            "published_at": "2026-07-30",
            "video_id": "video-fallback",
            "url": "https://youtu.be/video-fallback",
            "stats": {
                "views": 321,
                "watch_time_min": 42.5,
                "avg_view_duration_sec": 100,
            },
        }
    ]
    collector.youtube_service.list_playlist_items_for_display.assert_called_once_with("UU_REF", max_results=10)
