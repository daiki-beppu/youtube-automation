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
MAX_SHUFFLE_SEED = 2**32 - 1

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
_FADEIN_CURVES = frozenset(
    {
        "tri",
        "qsin",
        "esin",
        "hsin",
        "log",
        "ipar",
        "qua",
        "cub",
        "squ",
        "cbr",
        "par",
        "exp",
        "iqsin",
        "ihsin",
        "dese",
        "desi",
        "losi",
        "sinc",
        "isinc",
        "nofade",
    }
)


@dataclass(frozen=True)
class AudioAdjustments:
    """Validated document while preserving keys owned by later Audio Studio stages."""

    tracks: dict[str, dict[str, object]]
    order: list[str] | None
    shuffle_seed: int | None
    pin_first: list[str]
    master: dict[str, object] | None
    finalize: dict[str, object] | None
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


def _validate_filename_list(value: object, context: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValidationError(f"audio-adjustments.json の {context} は filename の配列である必要があります")
    for filename in value:
        _validate_filename(filename)
    if len(set(value)) != len(value):
        raise ValidationError(f"audio-adjustments.json の {context} に重複した filename があります")
    return list(value)


def _validate_shuffle_seed(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("audio-adjustments.json の shuffle_seed は integer である必要があります")
    if not 0 <= value <= MAX_SHUFFLE_SEED:
        raise ValidationError(f"audio-adjustments.json の shuffle_seed は 0..{MAX_SHUFFLE_SEED} で指定してください")
    return value


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


def validate_master_settings(value: object) -> dict[str, object]:
    """Validate the complete EQ / loudnorm / limiter settings for master adjustment."""
    raw = _mapping(value, "master settings")
    expected_sections = {"eq", "loudnorm", "limiter"}
    if set(raw) != expected_sections:
        missing = expected_sections - set(raw)
        unknown = set(raw) - expected_sections
        raise ValidationError(
            f"master settings の section が不正です: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    result: dict[str, object] = {}
    for section in sorted(expected_sections):
        fields = _NESTED_FIELDS[section]
        section_raw = _mapping(raw[section], f"master settings.{section}")
        if set(section_raw) != fields.keys():
            missing = fields.keys() - set(section_raw)
            unknown = set(section_raw) - fields.keys()
            raise ValidationError(
                f"master settings.{section} の field が不正です: missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        result[section] = {
            name: _validate_scalar(
                item,
                fields[name][0],
                fields[name][1],
                fields[name][2],
                f"master settings.{section}.{name}",
            )
            for name, item in section_raw.items()
        }
    return result


def master_settings_from_cleanup(settings: object) -> dict[str, object]:
    """Project full cleanup defaults onto the master-adjustable sections."""
    cleanup = validate_cleanup_settings(settings, partial=False)
    return validate_master_settings({section: cleanup[section] for section in ("eq", "loudnorm", "limiter")})


def _validate_fadein_curve(value: object, context: str) -> str:
    if not isinstance(value, str) or value not in _FADEIN_CURVES:
        raise ValidationError(f"{context} が不正です: {value!r}")
    return value


def validate_finalize_settings(value: object) -> dict[str, object]:
    """Validate complete collection-level ambient finalize settings."""
    raw = _mapping(value, "finalize settings")
    expected_sections = {"ambient_layers", "loudnorm", "mix"}
    if set(raw) != expected_sections:
        raise ValidationError(
            "finalize settings の section が不正です: "
            f"missing={sorted(expected_sections - set(raw))}, unknown={sorted(set(raw) - expected_sections)}"
        )

    ambient = _mapping(raw["ambient_layers"], "finalize settings.ambient_layers")
    ambient_fields = {"dirname", "glob", "volume_db", "fadein_s", "fadein_curve", "layers"}
    if set(ambient) != ambient_fields:
        raise ValidationError(
            "finalize settings.ambient_layers の field が不正です: "
            f"missing={sorted(ambient_fields - set(ambient))}, unknown={sorted(set(ambient) - ambient_fields)}"
        )
    dirname = ambient["dirname"]
    if (
        not isinstance(dirname, str)
        or not dirname
        or dirname in {".", ".."}
        or PurePath(dirname).name != dirname
        or "/" in dirname
        or "\\" in dirname
        or "\x00" in dirname
    ):
        raise ValidationError("finalize settings.ambient_layers.dirname は単一 directory 名で指定してください")
    glob_pattern = ambient["glob"]
    if (
        not isinstance(glob_pattern, str)
        or not glob_pattern
        or "/" in glob_pattern
        or "\\" in glob_pattern
        or "\x00" in glob_pattern
    ):
        raise ValidationError("finalize settings.ambient_layers.glob は directory を含まない pattern にしてください")
    raw_layers = _mapping(ambient["layers"], "finalize settings.ambient_layers.layers")
    layers: dict[str, object] = {}
    layer_fields = {"volume_db", "fadein_s", "fadein_curve"}
    for filename, override_value in raw_layers.items():
        _validate_filename(filename)
        override = _mapping(override_value, f"finalize settings.ambient_layers.layers.{filename}")
        if not override or set(override) - layer_fields:
            raise ValidationError(
                f"finalize settings.ambient_layers.layers.{filename} は既知 field を1件以上含めてください"
            )
        validated_override: dict[str, object] = {}
        if "volume_db" in override:
            validated_override["volume_db"] = _validate_scalar(
                override["volume_db"], float, -60, 12, f"finalize settings layer {filename}.volume_db"
            )
        if "fadein_s" in override:
            validated_override["fadein_s"] = _validate_scalar(
                override["fadein_s"], float, 0, 60, f"finalize settings layer {filename}.fadein_s"
            )
        if "fadein_curve" in override:
            validated_override["fadein_curve"] = _validate_fadein_curve(
                override["fadein_curve"], f"finalize settings layer {filename}.fadein_curve"
            )
        layers[filename] = validated_override

    loudnorm = _mapping(raw["loudnorm"], "finalize settings.loudnorm")
    loudnorm_fields = {"enabled", "mode", "I", "LRA", "TP"}
    if set(loudnorm) != loudnorm_fields:
        raise ValidationError("finalize settings.loudnorm は enabled / mode / I / LRA / TP が必須です")
    if loudnorm["mode"] != "linear":
        raise ValidationError("finalize settings.loudnorm.mode は linear のみ指定できます")

    mix = _mapping(raw["mix"], "finalize settings.mix")
    if set(mix) != {"duration", "normalize"}:
        raise ValidationError("finalize settings.mix は duration / normalize が必須です")
    if mix["duration"] not in {"first", "shortest", "longest"}:
        raise ValidationError("finalize settings.mix.duration が不正です")

    return {
        "ambient_layers": {
            "dirname": dirname,
            "glob": glob_pattern,
            "volume_db": _validate_scalar(
                ambient["volume_db"], float, -60, 12, "finalize settings.ambient_layers.volume_db"
            ),
            "fadein_s": _validate_scalar(
                ambient["fadein_s"], float, 0, 60, "finalize settings.ambient_layers.fadein_s"
            ),
            "fadein_curve": _validate_fadein_curve(
                ambient["fadein_curve"], "finalize settings.ambient_layers.fadein_curve"
            ),
            "layers": layers,
        },
        "loudnorm": {
            "enabled": _validate_scalar(loudnorm["enabled"], bool, None, None, "finalize settings.loudnorm.enabled"),
            "mode": "linear",
            "I": _validate_scalar(loudnorm["I"], float, -70, -5, "finalize settings.loudnorm.I"),
            "LRA": _validate_scalar(loudnorm["LRA"], float, 1, 50, "finalize settings.loudnorm.LRA"),
            "TP": _validate_scalar(loudnorm["TP"], float, -9, 0, "finalize settings.loudnorm.TP"),
        },
        "mix": {
            "duration": mix["duration"],
            "normalize": _validate_scalar(mix["normalize"], bool, None, None, "finalize settings.mix.normalize"),
        },
    }


def read_audio_adjustments(path: Path) -> AudioAdjustments:
    """Read the adjustments document, treating absence as an empty document."""
    if not path.exists():
        return AudioAdjustments(
            tracks={}, order=None, shuffle_seed=None, pin_first=[], master=None, finalize=None, extra={}
        )
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
    order = _validate_filename_list(root["order"], "order") if "order" in root else None
    pin_first = _validate_filename_list(root.get("pin_first", []), "pin_first")
    shuffle_seed = _validate_shuffle_seed(root.get("shuffle_seed"))
    master = validate_master_settings(root["master"]) if "master" in root else None
    finalize = validate_finalize_settings(root["finalize"]) if "finalize" in root else None
    if order is not None:
        unknown_pins = set(pin_first) - set(order)
        if unknown_pins:
            raise ValidationError(
                "audio-adjustments.json の pin_first が order にない filename を含みます: "
                f"{', '.join(sorted(unknown_pins))}"
            )
        if order[: len(pin_first)] != pin_first:
            raise ValidationError("audio-adjustments.json の pin_first は order の先頭と同じ順序である必要があります")
    elif pin_first or shuffle_seed is not None:
        raise ValidationError("audio-adjustments.json の pin_first / shuffle_seed には order が必要です")
    owned_keys = {"schema_version", "tracks", "order", "shuffle_seed", "pin_first", "master", "finalize"}
    extra = {key: value for key, value in root.items() if key not in owned_keys}
    return AudioAdjustments(
        tracks=tracks,
        order=order,
        shuffle_seed=shuffle_seed,
        pin_first=pin_first,
        master=master,
        finalize=finalize,
        extra=extra,
    )


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


def apply_track_order(files: list[Path], order: list[str] | None) -> list[Path]:
    """Apply an exact persisted filename order and fail loudly on collection drift."""
    if order is None:
        return files
    by_name = {path.name: path for path in files}
    requested = set(order)
    available = set(by_name)
    if len(order) != len(requested) or requested != available:
        missing = sorted(available - requested)
        unknown = sorted(requested - available)
        raise ValidationError(
            f"audio-adjustments.json の order と実ファイルが一致しません (missing={missing}, unknown={unknown})"
        )
    return [by_name[name] for name in order]


def _write_audio_adjustments(path: Path, document: AudioAdjustments) -> None:
    if path.is_symlink():
        raise ValidationError(f"audio-adjustments.json の symlink には書き込めません: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"schema_version": SCHEMA_VERSION, "tracks": document.tracks}
    if document.order is not None:
        payload["order"] = document.order
    if document.shuffle_seed is not None:
        payload["shuffle_seed"] = document.shuffle_seed
    if document.pin_first:
        payload["pin_first"] = document.pin_first
    if document.master is not None:
        payload["master"] = document.master
    if document.finalize is not None:
        payload["finalize"] = document.finalize
    payload.update(document.extra)
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
    updated = AudioAdjustments(
        tracks=tracks,
        order=document.order,
        shuffle_seed=document.shuffle_seed,
        pin_first=document.pin_first,
        master=document.master,
        finalize=document.finalize,
        extra=document.extra,
    )
    _write_audio_adjustments(path, updated)
    return updated


def replace_track_order(
    path: Path,
    order: object,
    shuffle_seed: object,
    pin_first: object,
) -> AudioAdjustments:
    """Atomically replace the persisted master order while preserving cleanup data."""
    validated_order = _validate_filename_list(order, "order")
    validated_pins = _validate_filename_list(pin_first, "pin_first")
    validated_seed = _validate_shuffle_seed(shuffle_seed)
    unknown_pins = set(validated_pins) - set(validated_order)
    if unknown_pins:
        raise ValidationError(
            "audio-adjustments.json の pin_first が order にない filename を含みます: "
            f"{', '.join(sorted(unknown_pins))}"
        )
    if validated_order[: len(validated_pins)] != validated_pins:
        raise ValidationError("audio-adjustments.json の pin_first は order の先頭と同じ順序である必要があります")
    document = read_audio_adjustments(path)
    updated = AudioAdjustments(
        tracks=document.tracks,
        order=validated_order,
        shuffle_seed=validated_seed,
        pin_first=validated_pins,
        master=document.master,
        finalize=document.finalize,
        extra=document.extra,
    )
    _write_audio_adjustments(path, updated)
    return updated


def replace_master_adjustments(path: Path, settings: object) -> AudioAdjustments:
    """Atomically replace complete master settings while preserving track and order stages."""
    document = read_audio_adjustments(path)
    updated = AudioAdjustments(
        tracks=document.tracks,
        order=document.order,
        shuffle_seed=document.shuffle_seed,
        pin_first=document.pin_first,
        master=validate_master_settings(settings),
        finalize=document.finalize,
        extra=document.extra,
    )
    _write_audio_adjustments(path, updated)
    return updated


def replace_finalize_adjustments(path: Path, settings: object) -> AudioAdjustments:
    """Atomically replace finalize settings while preserving all other Audio Studio stages."""
    document = read_audio_adjustments(path)
    updated = AudioAdjustments(
        tracks=document.tracks,
        order=document.order,
        shuffle_seed=document.shuffle_seed,
        pin_first=document.pin_first,
        master=document.master,
        finalize=validate_finalize_settings(settings),
        extra=document.extra,
    )
    _write_audio_adjustments(path, updated)
    return updated
