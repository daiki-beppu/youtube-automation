"""yt-captions-upload CLI のテスト。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.helpers.video_description import write_video_description_pair
from youtube_automation.commands.youtube import captions_upload
from youtube_automation.commands.youtube.captions_upload import main
from youtube_automation.core.errors import YouTubeAPIError


def test_dry_run_generates_srt_without_youtube_api(tmp_path, monkeypatch):
    lyrics = tmp_path / "suno-lyrics.json"
    lyrics.write_text(
        json.dumps(
            [
                {"name": "First", "lyrics": "[Verse]\nHello"},
                {"name": "Second", "lyrics": "[Verse]\nAgain"},
            ]
        ),
        encoding="utf-8",
    )
    descriptions = write_video_description_pair(
        tmp_path,
        description="🎵 Album - 2 tracks, 04:00\n00:00 First\n02:00 Second",
        tracks=[
            {"position": 1, "start": "00:00", "title": "First"},
            {"position": 2, "start": "02:00", "title": "Second"},
        ],
    )
    output = tmp_path / "out.srt"

    code = main(
        [
            "--video-id",
            "video-1",
            "--lyrics",
            str(lyrics),
            "--descriptions",
            str(descriptions),
            "--language",
            "en",
            "--output",
            str(output),
            "--dry-run",
        ]
    )

    assert code == 0
    assert output.read_text(encoding="utf-8").count(" --> ") == 2


def _cli_files(tmp_path, *, include_duration=True):
    lyrics = tmp_path / "lyrics.txt"
    lyrics.write_text("Hello", encoding="utf-8")
    duration = ", 01:00" if include_duration else ""
    descriptions = write_video_description_pair(
        tmp_path,
        description=f"🎵 One track{duration}\n00:00 First",
        tracks=[{"position": 1, "start": "00:00", "title": "First"}],
    )
    return lyrics, descriptions


def test_end_time_allows_apply_when_description_has_no_duration(tmp_path, monkeypatch):
    lyrics, descriptions = _cli_files(tmp_path, include_duration=False)
    clients = SimpleNamespace(youtube=object())
    upload = MagicMock(return_value=SimpleNamespace(action="inserted", caption_id="cap-1"))
    monkeypatch.setattr(captions_upload, "create_authenticated_youtube_clients", lambda: clients)
    monkeypatch.setattr(captions_upload, "upload_caption", upload)

    code = main(
        [
            "--video-id",
            "video-1",
            "--lyrics",
            str(lyrics),
            "--descriptions",
            str(descriptions),
            "--language",
            "ja",
            "--name",
            "Japanese lyrics",
            "--end-time",
            "01:00",
            "--existing",
            "update",
            "--apply",
        ]
    )

    assert code == 0
    upload.assert_called_once_with(
        clients.youtube,
        video_id="video-1",
        language="ja",
        name="Japanese lyrics",
        srt_path=tmp_path / "captions.ja.srt",
        existing_policy="update",
        confirm_update=captions_upload._confirm_update,
    )


def test_missing_duration_without_end_time_exits_one_without_api(tmp_path, monkeypatch):
    lyrics, descriptions = _cli_files(tmp_path, include_duration=False)
    auth = MagicMock()
    monkeypatch.setattr(captions_upload, "create_authenticated_youtube_clients", auth)

    code = main(
        [
            "--video-id",
            "video-1",
            "--lyrics",
            str(lyrics),
            "--descriptions",
            str(descriptions),
            "--language",
            "en",
            "--apply",
        ]
    )

    assert code == 1
    auth.assert_not_called()


@pytest.mark.parametrize("policy", ["ask", "update", "skip"])
def test_apply_forwards_each_existing_policy(tmp_path, monkeypatch, policy):
    lyrics, descriptions = _cli_files(tmp_path)
    upload = MagicMock(return_value=SimpleNamespace(action="skipped", caption_id="cap-1"))
    monkeypatch.setattr(
        captions_upload,
        "create_authenticated_youtube_clients",
        lambda: SimpleNamespace(youtube="youtube"),
    )
    monkeypatch.setattr(captions_upload, "upload_caption", upload)

    code = main(
        [
            "--video-id",
            "video-1",
            "--lyrics",
            str(lyrics),
            "--descriptions",
            str(descriptions),
            "--language",
            "en",
            "--existing",
            policy,
            "--apply",
        ]
    )

    assert code == 0
    assert upload.call_args.kwargs["existing_policy"] == policy


@pytest.mark.parametrize("error", [YouTubeAPIError("API failed"), OSError("disk full")])
def test_apply_failure_returns_one(tmp_path, monkeypatch, error):
    lyrics, descriptions = _cli_files(tmp_path)
    monkeypatch.setattr(
        captions_upload,
        "create_authenticated_youtube_clients",
        lambda: SimpleNamespace(youtube="youtube"),
    )
    monkeypatch.setattr(captions_upload, "upload_caption", MagicMock(side_effect=error))

    assert (
        main(
            [
                "--video-id",
                "video-1",
                "--lyrics",
                str(lyrics),
                "--descriptions",
                str(descriptions),
                "--language",
                "en",
                "--apply",
            ]
        )
        == 1
    )
