from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.media.audio_adjustments import (
    AudioAdjustments,
    read_audio_adjustments,
    replace_track_cleanup_overrides,
    validate_cleanup_settings,
)


def _settings() -> dict[str, object]:
    return {
        "eq": {
            "enabled": True,
            "muddiness_freq_hz": 350,
            "muddiness_gain_db": -2.0,
            "harshness_freq_hz": 8000,
            "harshness_gain_db": -1.5,
        },
        "loudnorm": {"enabled": True, "I": -14.0, "LRA": 11.0, "TP": -1.5},
        "limiter": {"enabled": True, "limit": 0.95},
        "trim_silence": {"enabled": True, "threshold_db": -50.0},
        "tail_fade_guard": {"enabled": True, "fade_sec": 3.0},
        "volume_smoothing": True,
    }


def test_missing_adjustments_file_is_an_empty_document(tmp_path: Path) -> None:
    document = read_audio_adjustments(tmp_path / "audio-adjustments.json")

    assert document == AudioAdjustments(tracks={}, extra={})


def test_replace_track_writes_only_values_changed_from_defaults(tmp_path: Path) -> None:
    path = tmp_path / "20-documentation" / "audio-adjustments.json"
    defaults = _settings()
    submitted = _settings()
    submitted["eq"] = {**submitted["eq"], "muddiness_gain_db": -4.0}
    submitted["limiter"] = {**submitted["limiter"], "enabled": False}

    saved = replace_track_cleanup_overrides(path, "01 Night.mp3", submitted, defaults)

    assert saved.tracks == {
        "01 Night.mp3": {
            "eq": {"muddiness_gain_db": -4.0},
            "limiter": {"enabled": False},
        }
    }
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "tracks": saved.tracks,
    }


def test_replacing_with_defaults_removes_track_and_preserves_future_top_level_keys(tmp_path: Path) -> None:
    path = tmp_path / "audio-adjustments.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tracks": {"01 Night.mp3": {"eq": {"muddiness_gain_db": -4}}},
                "track_order": ["01 Night.mp3"],
            }
        ),
        encoding="utf-8",
    )

    saved = replace_track_cleanup_overrides(path, "01 Night.mp3", _settings(), _settings())

    assert saved.tracks == {}
    assert saved.extra == {"track_order": ["01 Night.mp3"]}
    assert json.loads(path.read_text(encoding="utf-8"))["track_order"] == ["01 Night.mp3"]


@pytest.mark.parametrize(
    "payload",
    [
        {"eq": {"muddiness_gain_db": "deep"}},
        {"eq": {"muddiness_gain_db": float("nan")}},
        {"eq": {"unknown": 1}},
        {"loudnorm": {"TP": 1}},
        {"volume_smoothing": 1},
        {"unknown": True},
    ],
)
def test_cleanup_settings_reject_invalid_shapes_and_values(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        validate_cleanup_settings(payload, partial=True)


def test_reader_rejects_path_like_track_names(tmp_path: Path) -> None:
    path = tmp_path / "audio-adjustments.json"
    path.write_text(
        json.dumps({"schema_version": 1, "tracks": {"../outside.mp3": {}}}),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="filename"):
        read_audio_adjustments(path)
