from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.media.audio_adjustments import (
    AudioAdjustments,
    read_audio_adjustments,
    replace_finalize_adjustments,
    replace_master_adjustments,
    replace_track_cleanup_overrides,
    replace_track_order,
    validate_cleanup_settings,
    validate_finalize_settings,
    validate_master_settings,
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


def _finalize_settings() -> dict[str, object]:
    return {
        "ambient_layers": {
            "dirname": "rain_layers",
            "glob": "rain_*.wav",
            "volume_db": -19.0,
            "fadein_s": 0.5,
            "fadein_curve": "tri",
            "layers": {"rain_001.wav": {"volume_db": -23.0}},
        },
        "loudnorm": {"enabled": True, "mode": "linear", "I": -14.0, "LRA": 11.0, "TP": -1.5},
        "mix": {"duration": "first", "normalize": False},
    }


def test_missing_adjustments_file_is_an_empty_document(tmp_path: Path) -> None:
    document = read_audio_adjustments(tmp_path / "audio-adjustments.json")

    assert document == AudioAdjustments(
        tracks={}, order=None, shuffle_seed=None, pin_first=[], master=None, finalize=None, extra={}
    )


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


def test_replace_track_order_preserves_cleanup_and_serializes_owned_keys(tmp_path: Path) -> None:
    path = tmp_path / "audio-adjustments.json"
    replace_track_cleanup_overrides(path, "01 First.mp3", _settings(), _settings())

    saved = replace_track_order(
        path,
        ["02 Second.wav", "01 First.mp3"],
        12345,
        ["02 Second.wav"],
    )

    assert saved.order == ["02 Second.wav", "01 First.mp3"]
    assert saved.shuffle_seed == 12345
    assert saved.pin_first == ["02 Second.wav"]
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "tracks": {},
        "order": ["02 Second.wav", "01 First.mp3"],
        "shuffle_seed": 12345,
        "pin_first": ["02 Second.wav"],
    }


def test_replace_master_adjustments_preserves_tracks_and_order(tmp_path: Path) -> None:
    path = tmp_path / "audio-adjustments.json"
    replace_track_order(path, ["01 First.mp3"], 123, ["01 First.mp3"])
    replace_track_cleanup_overrides(path, "01 First.mp3", _settings(), _settings())
    master = {key: _settings()[key] for key in ("eq", "loudnorm", "limiter")}

    saved = replace_master_adjustments(path, master)

    assert saved.master == master
    assert saved.order == ["01 First.mp3"]
    assert saved.shuffle_seed == 123
    assert saved.pin_first == ["01 First.mp3"]
    assert json.loads(path.read_text(encoding="utf-8"))["master"] == master


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"eq": {}, "loudnorm": {}, "limiter": {}},
        {**{key: _settings()[key] for key in ("eq", "loudnorm", "limiter")}, "unknown": {}},
    ],
)
def test_master_settings_reject_incomplete_or_unknown_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        validate_master_settings(payload)


def test_replace_finalize_adjustments_preserves_other_stages(tmp_path: Path) -> None:
    path = tmp_path / "audio-adjustments.json"
    replace_track_order(path, ["01 First.mp3"], 123, ["01 First.mp3"])
    master = {key: _settings()[key] for key in ("eq", "loudnorm", "limiter")}
    replace_master_adjustments(path, master)

    saved = replace_finalize_adjustments(path, _finalize_settings())

    assert saved.finalize == _finalize_settings()
    assert saved.master == master
    assert saved.order == ["01 First.mp3"]
    assert json.loads(path.read_text(encoding="utf-8"))["finalize"] == _finalize_settings()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"unknown": {}}),
        lambda value: value["ambient_layers"].update({"dirname": "../outside"}),
        lambda value: value["ambient_layers"].update({"glob": "../*.wav"}),
        lambda value: value["ambient_layers"].update({"fadein_curve": "mystery"}),
        lambda value: value["loudnorm"].update({"mode": "dynamic"}),
        lambda value: value["mix"].update({"duration": "forever"}),
        lambda value: value["mix"].update({"normalize": 1}),
    ],
)
def test_finalize_settings_reject_invalid_values(mutate) -> None:
    payload = _finalize_settings()
    mutate(payload)

    with pytest.raises(ValidationError):
        validate_finalize_settings(payload)


@pytest.mark.parametrize(
    ("order", "seed", "pins"),
    [
        (["01.mp3", "01.mp3"], None, []),
        (["../01.mp3"], None, []),
        (["01.mp3"], True, []),
        (["01.mp3"], -1, []),
        (["01.mp3"], 2**32, []),
        (["01.mp3", "02.mp3"], None, ["02.mp3"]),
        (["01.mp3"], None, ["missing.mp3"]),
    ],
)
def test_replace_track_order_rejects_invalid_metadata(
    tmp_path: Path,
    order: list[str],
    seed: object,
    pins: list[str],
) -> None:
    with pytest.raises(ValidationError):
        replace_track_order(tmp_path / "audio-adjustments.json", order, seed, pins)
