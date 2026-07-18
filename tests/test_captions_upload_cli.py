"""yt-captions-upload CLI のテスト。"""

from __future__ import annotations

import json

from youtube_automation.scripts.captions_upload import main


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
    descriptions = tmp_path / "descriptions.md"
    descriptions.write_text(
        "## Complete Collection 概要欄\n\n```\n🎵 Album - 2 tracks, 04:00\n00:00 First\n02:00 Second\n```\n",
        encoding="utf-8",
    )
    output = tmp_path / "out.srt"
    monkeypatch.setattr(
        "youtube_automation.scripts.captions_upload.get_youtube",
        lambda: (_ for _ in ()).throw(AssertionError("API must not be called")),
    )

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
