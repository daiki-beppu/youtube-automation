"""Validated per-track cleanup adjustments for Audio Studio."""

from __future__ import annotations

import json
import math
import os
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePath

from youtube_automation.core.errors import ValidationError

SCHEMA_VERSION = 1

_NESTED_FIELDS: dict[str, dict[str, tuple[type[object], float | None, float | None]]] = {
    "eq": {
        "enabled": (bool, None, None),
        "muddiness_freq_hz": (int, 20, 20_000),
        "muddiness_gain_db": (float, -24, 24),
        "harshness_freq_hz": (int, 20, 20_000),
        "harshness_gain_db": (float, -24, 24),
    },
    "loudnorm": {
        "enabled": (bool, None, None),
        "I": (float, -70, -5),
        "LRA": (float, 1, 50),
        "TP": (float, -9, 0),
    },
    "limiter": {"enabled": (bool, None, None), "limit": (float, 0.01, 1)},
    "trim_silence": {"enabled": (bool, None, None), "threshold_db": (float, -100, 0)},
    "tail_fade_guard": {"enabled": (bool, None, None), "fade_sec": (float, 0, 60)},
}
_BOOLEAN_FIELDS = frozenset({"volume_smoothing"})
_ALL_FIELDS = frozenset(_NESTED_FIELDS) | _BOOLEAN_FIELDS


@dataclass(frozen=True)
class AudioAdjustments:
    """Validated document while preserving keys owned by later Audio Studio stages."""

    tracks: dict[str, dict[str, object]]
    extra: dict[str, object]


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"audio-adjustments.json の {context} は object である必要があります")
    if any(not isinstance(key, str) for key in value):
        raise ValidationError(f"audio-adjustments.json の {context} のキーは string である必要があります")
    return value


def _validate_filename(filename: str) -> None:
    if (
        not filename
        or filename in {".", ".."}
        or PurePath(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
    ):
        raise ValidationError(f"audio-adjustments.json の track filename が不正です: {filename!r}")


def _validate_scalar(
    value: object,
    expected_type: type[object],
    minimum: float | None,
    maximum: float | None,
    context: str,
) -> object:
    if expected_type is bool:
        if not isinstance(value, bool):
            raise ValidationError(f"{context} は boolean である必要があります")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{context} は number である必要があります")
    if expected_type is int and not isinstance(value, int):
        raise ValidationError(f"{context} は integer である必要があります")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValidationError(f"{context} は有限の number である必要があります")
    if (minimum is not None and numeric < minimum) or (maximum is not None and numeric > maximum):
        raise ValidationError(f"{context} は {minimum:g}..{maximum:g} の範囲で指定してください")
    return value


def validate_cleanup_settings(value: object, *, partial: bool) -> dict[str, object]:
    """Validate full UI settings or a persisted partial override."""
    raw = _mapping(value, "cleanup settings")
    unknown = set(raw) - _ALL_FIELDS
    if unknown:
        raise ValidationError(f"cleanup settings に未知のキーがあります: {', '.join(sorted(unknown))}")
    if not partial and set(raw) != _ALL_FIELDS:
        missing = _ALL_FIELDS - set(raw)
        raise ValidationError(f"cleanup settings に必須キーがありません: {', '.join(sorted(missing))}")

    result: dict[str, object] = {}
    for section, fields in _NESTED_FIELDS.items():
        if section not in raw:
            continue
        section_raw = _mapping(raw[section], f"cleanup settings.{section}")
        section_unknown = set(section_raw) - fields.keys()
        if section_unknown:
            raise ValidationError(
                f"cleanup settings.{section} に未知のキーがあります: {', '.join(sorted(section_unknown))}"
            )
        if not partial and set(section_raw) != fields.keys():
            missing = fields.keys() - set(section_raw)
            raise ValidationError(f"cleanup settings.{section} に必須キーがありません: {', '.join(sorted(missing))}")
        validated_section: dict[str, object] = {}
        for name, item in section_raw.items():
            expected_type, minimum, maximum = fields[name]
            validated_section[name] = _validate_scalar(
                item,
                expected_type,
                minimum,
                maximum,
                f"cleanup settings.{section}.{name}",
            )
        if validated_section:
            result[section] = validated_section

    for name in _BOOLEAN_FIELDS:
        if name in raw:
            result[name] = _validate_scalar(raw[name], bool, None, None, f"cleanup settings.{name}")
    return result


def read_audio_adjustments(path: Path) -> AudioAdjustments:
    """Read the adjustments document, treating absence as an empty document."""
    if not path.exists():
        return AudioAdjustments(tracks={}, extra={})
    if path.is_symlink() or not path.is_file():
        raise ValidationError(f"audio-adjustments.json は通常ファイルである必要があります: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"audio-adjustments.json を読み込めません: {error}") from error
    root = _mapping(payload, "root")
    if root.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise ValidationError(f"未対応の audio-adjustments schema_version: {root.get('schema_version')!r}")
    raw_tracks = _mapping(root.get("tracks", {}), "tracks")
    tracks: dict[str, dict[str, object]] = {}
    for filename, value in raw_tracks.items():
        _validate_filename(filename)
        tracks[filename] = validate_cleanup_settings(value, partial=True)
    extra = {key: value for key, value in root.items() if key not in {"schema_version", "tracks"}}
    return AudioAdjustments(tracks=tracks, extra=extra)


def cleanup_settings_diff(settings: object, defaults: object) -> dict[str, object]:
    """Return only adjustable values that differ from validated defaults."""
    current = validate_cleanup_settings(settings, partial=False)
    baseline = validate_cleanup_settings(defaults, partial=False)
    result: dict[str, object] = {}
    for key in sorted(_ALL_FIELDS):
        current_value = current[key]
        baseline_value = baseline[key]
        if isinstance(current_value, dict) and isinstance(baseline_value, dict):
            nested = {name: value for name, value in current_value.items() if value != baseline_value[name]}
            if nested:
                result[key] = nested
        elif current_value != baseline_value:
            result[key] = current_value
    return result


def merge_cleanup_settings(defaults: object, overrides: object) -> dict[str, object]:
    """Apply a validated partial override to a full cleanup settings mapping."""
    baseline = validate_cleanup_settings(defaults, partial=False)
    overlay = validate_cleanup_settings(overrides, partial=True)
    merged: dict[str, object] = {}
    for key, baseline_value in baseline.items():
        overlay_value = overlay.get(key)
        if isinstance(baseline_value, dict) and isinstance(overlay_value, dict):
            merged[key] = {**baseline_value, **overlay_value}
        elif overlay_value is not None:
            merged[key] = overlay_value
        else:
            merged[key] = baseline_value
    return merged


def _write_audio_adjustments(path: Path, document: AudioAdjustments) -> None:
    if path.is_symlink():
        raise ValidationError(f"audio-adjustments.json の symlink には書き込めません: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SCHEMA_VERSION, "tracks": document.tracks, **document.extra}
    existing_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_path, existing_mode)
        os.replace(temporary_path, path)
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise ValidationError(f"audio-adjustments.json を保存できません: {error}") from error


def replace_track_cleanup_overrides(
    path: Path,
    filename: str,
    settings: object,
    defaults: object,
) -> AudioAdjustments:
    """Atomically replace one track's cleanup diff while preserving other stages."""
    _validate_filename(filename)
    document = read_audio_adjustments(path)
    tracks = dict(document.tracks)
    overrides = cleanup_settings_diff(settings, defaults)
    if overrides:
        tracks[filename] = overrides
    else:
        tracks.pop(filename, None)
    updated = AudioAdjustments(tracks=tracks, extra=document.extra)
    _write_audio_adjustments(path, updated)
    return updated
