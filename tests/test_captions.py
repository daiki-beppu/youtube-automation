"""歌詞 SRT 生成と caption track upsert のテスト。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from youtube_automation.domains.media.captions import (
    generate_srt,
    parse_total_duration,
    parse_track_timestamps,
)
from youtube_automation.infrastructure import captions_adapter
from youtube_automation.infrastructure.captions_adapter import upload_caption
from youtube_automation.infrastructure.errors import ValidationError, YouTubeAPIError

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


@pytest.mark.parametrize("total_duration_ms", [0, 9_999])
def test_generate_srt_rejects_final_duration_before_last_track_start(total_duration_ms):
    with pytest.raises(ValidationError, match="最後のトラック開始時刻以降"):
        generate_srt(["a"], [10_000], total_duration_ms)


def test_generate_srt_allows_final_duration_equal_to_last_track_start():
    result = generate_srt(["a"], [10_000], 10_000)

    assert "00:00:10,000 --> 00:00:10,000" in result


@pytest.mark.parametrize("total_duration_ms", [-1, 10_000.0, True])
def test_generate_srt_rejects_non_integer_total_duration(total_duration_ms):
    with pytest.raises(ValidationError, match="整数ミリ秒"):
        generate_srt(["a"], [0], total_duration_ms)


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
    monkeypatch.setattr("youtube_automation.infrastructure.captions_adapter.log_quota", quota)

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
    monkeypatch.setattr("youtube_automation.infrastructure.captions_adapter.log_quota", MagicMock())

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
    monkeypatch.setattr("youtube_automation.infrastructure.captions_adapter.log_quota", MagicMock())

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
    monkeypatch.setattr("youtube_automation.infrastructure.captions_adapter.log_quota", MagicMock())

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


def test_upload_caption_ask_can_choose_update(tmp_path, monkeypatch):
    existing = {"id": "existing-caption", "snippet": {"language": "en", "name": "Old"}}
    youtube = _youtube_with_captions([existing])
    monkeypatch.setattr("youtube_automation.infrastructure.captions_adapter.log_quota", MagicMock())

    result = upload_caption(
        youtube,
        video_id="video-1",
        language="en",
        name="English lyrics",
        srt_path=_srt(tmp_path),
        existing_policy="ask",
        confirm_update=lambda item: item is existing,
    )

    assert result.action == "updated"
    youtube.captions.return_value.update.assert_called_once()


def test_upload_caption_rejects_ambiguous_existing_tracks(tmp_path, monkeypatch):
    youtube = _youtube_with_captions(
        [
            {"id": "one", "snippet": {"language": "en"}},
            {"id": "two", "snippet": {"language": "en"}},
        ]
    )
    monkeypatch.setattr("youtube_automation.infrastructure.captions_adapter.log_quota", MagicMock())

    with pytest.raises(ValidationError, match="複数"):
        upload_caption(
            youtube,
            video_id="video-1",
            language="en",
            name="English lyrics",
            srt_path=_srt(tmp_path),
            existing_policy="update",
        )


def _http_error(status: int = 503) -> HttpError:
    response = MagicMock()
    response.status = status
    response.reason = "Service Unavailable"
    return HttpError(
        resp=response,
        content=b'{"error": {"errors": [{"reason": "backendError"}]}}',
    )


@pytest.mark.parametrize(
    ("overrides", "error_match"),
    [
        ({"existing_policy": "invalid"}, "existing_policy"),
        ({"language": "   "}, "字幕言語"),
        ({"name": ""}, "字幕トラック名"),
        ({"name": "x" * 151}, "字幕トラック名"),
    ],
)
def test_upload_caption_rejects_invalid_inputs_before_api_call(tmp_path, overrides, error_match):
    youtube = MagicMock()
    arguments = {
        "video_id": "video-1",
        "language": "en",
        "name": "English lyrics",
        "srt_path": _srt(tmp_path),
        "existing_policy": "skip",
        **overrides,
    }

    with pytest.raises(ValidationError, match=error_match):
        upload_caption(youtube, **arguments)

    youtube.captions.assert_not_called()


def test_upload_caption_rejects_missing_srt_before_api_call(tmp_path):
    youtube = MagicMock()

    with pytest.raises(ValidationError, match="SRT ファイルが見つかりません"):
        upload_caption(
            youtube,
            video_id="video-1",
            language="en",
            name="English lyrics",
            srt_path=tmp_path / "missing.srt",
            existing_policy="skip",
        )

    youtube.captions.assert_not_called()


def test_upload_caption_ask_requires_callback_before_mutation(tmp_path, monkeypatch):
    existing = {"id": "existing-caption", "snippet": {"language": "en"}}
    youtube = _youtube_with_captions([existing])
    monkeypatch.setattr(captions_adapter, "log_quota", MagicMock())

    with pytest.raises(ValidationError, match="confirm_update"):
        upload_caption(
            youtube,
            video_id="video-1",
            language="en",
            name="English lyrics",
            srt_path=_srt(tmp_path),
            existing_policy="ask",
        )

    youtube.captions.return_value.insert.assert_not_called()
    youtube.captions.return_value.update.assert_not_called()


def test_caption_list_http_error_is_converted_and_records_failed_quota(tmp_path, monkeypatch):
    youtube = _youtube_with_captions([])
    youtube.captions.return_value.list.return_value.execute.side_effect = _http_error(429)
    quota = MagicMock()
    monkeypatch.setattr(captions_adapter, "log_quota", quota)

    with pytest.raises(YouTubeAPIError) as error_info:
        upload_caption(
            youtube,
            video_id="video-1",
            language="en",
            name="English lyrics",
            srt_path=_srt(tmp_path),
            existing_policy="skip",
        )

    assert error_info.value.status_code == 429
    assert error_info.value.reason == "backendError"
    assert isinstance(error_info.value.__cause__, HttpError)
    quota.assert_called_once_with(
        "youtube-data-api",
        "captions.list",
        50,
        metadata={"video_id": "video-1", "language": "en", "error": True},
    )


@pytest.mark.parametrize(
    ("existing", "policy", "operation", "units"),
    [
        ([], "skip", "captions.insert", 400),
        ([{"id": "caption-1", "snippet": {"language": "en"}}], "update", "captions.update", 450),
    ],
)
def test_caption_mutation_http_error_is_converted_and_records_failed_quota(
    tmp_path,
    monkeypatch,
    existing,
    policy,
    operation,
    units,
):
    youtube = _youtube_with_captions(existing)
    request = (
        youtube.captions.return_value.insert.return_value
        if operation == "captions.insert"
        else youtube.captions.return_value.update.return_value
    )
    request.execute.side_effect = _http_error()
    quota = MagicMock()
    monkeypatch.setattr(captions_adapter, "log_quota", quota)
    monkeypatch.setattr(captions_adapter, "MediaFileUpload", MagicMock())

    with pytest.raises(YouTubeAPIError, match=operation) as error_info:
        upload_caption(
            youtube,
            video_id="video-1",
            language="en",
            name="English lyrics",
            srt_path=_srt(tmp_path),
            existing_policy=policy,
        )

    assert error_info.value.status_code == 503
    assert isinstance(error_info.value.__cause__, HttpError)
    assert quota.call_args_list[-1].args == ("youtube-data-api", operation, units)
    assert quota.call_args_list[-1].kwargs == {
        "metadata": {
            "video_id": "video-1",
            "language": "en",
            "error": True,
        }
    }
