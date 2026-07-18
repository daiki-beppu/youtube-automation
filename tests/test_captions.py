"""歌詞 SRT 生成と caption track upsert のテスト。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from youtube_automation.utils.captions import (
    generate_srt,
    parse_total_duration,
    parse_track_timestamps,
    upload_caption,
)
from youtube_automation.utils.exceptions import ValidationError

_DESCRIPTIONS = """## Complete Collection 概要欄

```
🎵 24-bit Night Songs - 2 tracks, 06:00

00:00 First Light
03:00 After Rain
```
"""


def test_generate_srt_is_ascending_and_ignores_suno_section_tags():
    tracks = parse_track_timestamps(_DESCRIPTIONS)
    result = generate_srt(["[Verse]\nHello\nWorld", "[Chorus]\nAgain\nHome"], tracks, 360_000)

    assert "1\n00:00:00,000 --> 00:01:30,000\nHello" in result
    assert "2\n00:01:30,000 --> 00:03:00,000\nWorld" in result
    assert "3\n00:03:00,000 --> 00:04:30,000\nAgain" in result
    assert result.endswith("00:06:00,000\nHome\n")
    assert "[Verse]" not in result
    assert result.count(" --> ") == 4


def test_parse_total_duration_from_description():
    assert parse_total_duration(_DESCRIPTIONS) == 360_000


def test_generate_srt_rejects_duplicate_track_starts():
    with pytest.raises(ValidationError, match="昇順かつ重複なし"):
        generate_srt(["a", "b"], [0, 0], 10_000)


def test_generate_srt_rejects_lyrics_track_count_mismatch():
    with pytest.raises(ValidationError, match="歌詞エントリ数"):
        generate_srt(["a"], [0, 10_000], 20_000)


def _youtube_with_captions(items: list[dict]) -> MagicMock:
    youtube = MagicMock()
    youtube.captions.return_value.list.return_value.execute.return_value = {"items": items}
    youtube.captions.return_value.insert.return_value.execute.return_value = {"id": "new-caption"}
    youtube.captions.return_value.update.return_value.execute.return_value = {"id": "existing-caption"}
    return youtube


def _srt(tmp_path: Path) -> Path:
    path = tmp_path / "captions.en.srt"
    path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    return path


def test_upload_caption_inserts_when_language_is_missing(tmp_path, monkeypatch):
    youtube = _youtube_with_captions([{"id": "ja-caption", "snippet": {"language": "ja"}}])
    quota = MagicMock()
    monkeypatch.setattr("youtube_automation.utils.captions.log_quota", quota)

    result = upload_caption(
        youtube,
        video_id="video-1",
        language="en",
        name="English lyrics",
        srt_path=_srt(tmp_path),
        existing_policy="skip",
    )

    assert result.action == "inserted"
    youtube.captions.return_value.insert.assert_called_once()
    youtube.captions.return_value.update.assert_not_called()
    assert [call.args[1] for call in quota.call_args_list] == ["captions.list", "captions.insert"]


def test_upload_caption_skips_existing_language_without_insert(tmp_path, monkeypatch):
    existing = {"id": "existing-caption", "snippet": {"language": "en", "name": "Old"}}
    youtube = _youtube_with_captions([existing])
    monkeypatch.setattr("youtube_automation.utils.captions.log_quota", MagicMock())

    result = upload_caption(
        youtube,
        video_id="video-1",
        language="en",
        name="English lyrics",
        srt_path=_srt(tmp_path),
        existing_policy="skip",
    )

    assert result.action == "skipped"
    assert result.caption_id == "existing-caption"
    youtube.captions.return_value.insert.assert_not_called()
    youtube.captions.return_value.update.assert_not_called()


def test_upload_caption_updates_existing_language(tmp_path, monkeypatch):
    existing = {"id": "existing-caption", "snippet": {"language": "en", "name": "Old"}}
    youtube = _youtube_with_captions([existing])
    monkeypatch.setattr("youtube_automation.utils.captions.log_quota", MagicMock())

    result = upload_caption(
        youtube,
        video_id="video-1",
        language="en",
        name="English lyrics",
        srt_path=_srt(tmp_path),
        existing_policy="update",
    )

    assert result.action == "updated"
    youtube.captions.return_value.update.assert_called_once()
    youtube.captions.return_value.insert.assert_not_called()


def test_upload_caption_ask_can_choose_skip(tmp_path, monkeypatch):
    existing = {"id": "existing-caption", "snippet": {"language": "en", "name": "Old"}}
    youtube = _youtube_with_captions([existing])
    monkeypatch.setattr("youtube_automation.utils.captions.log_quota", MagicMock())

    result = upload_caption(
        youtube,
        video_id="video-1",
        language="en",
        name="English lyrics",
        srt_path=_srt(tmp_path),
        existing_policy="ask",
        confirm_update=lambda _item: False,
    )

    assert result.action == "skipped"
    youtube.captions.return_value.update.assert_not_called()


def test_upload_caption_rejects_ambiguous_existing_tracks(tmp_path, monkeypatch):
    youtube = _youtube_with_captions(
        [
            {"id": "one", "snippet": {"language": "en"}},
            {"id": "two", "snippet": {"language": "en"}},
        ]
    )
    monkeypatch.setattr("youtube_automation.utils.captions.log_quota", MagicMock())

    with pytest.raises(ValidationError, match="複数"):
        upload_caption(
            youtube,
            video_id="video-1",
            language="en",
            name="English lyrics",
            srt_path=_srt(tmp_path),
            existing_policy="update",
        )
