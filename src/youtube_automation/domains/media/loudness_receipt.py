"""Versioned receipt for a completed collection loudness scan."""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from youtube_automation.core.errors import ConfigError, ValidationError
from youtube_automation.domains.media.audio_formats import AUDIO_EXTS

RECEIPT_SCHEMA_VERSION = 1
RAW_MASTER_OUTPUT_NAME = "master.mp3"
_DEFAULT_MAX_DEVIATION_LU = 2.0


def _as_mapping(value: object, context: str) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"skill-config の {context} は mapping である必要があります: {value!r}")
    return value


def resolve_max_deviation_lu(config: Mapping[str, object]) -> float:
    """Resolve and validate the deviation threshold from merged skill config."""
    validation = _as_mapping(config.get("validation"), "validation")
    loudness = _as_mapping(validation.get("loudness_deviation"), "validation.loudness_deviation")
    raw_value = loudness.get("max_lu", _DEFAULT_MAX_DEVIATION_LU)
    if isinstance(raw_value, bool):
        raise ConfigError("validation.loudness_deviation.max_lu は 0 より大きい数値で指定してください")
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as error:
        raise ConfigError("validation.loudness_deviation.max_lu は 0 より大きい数値で指定してください") from error
    if not math.isfinite(value) or value <= 0:
        raise ConfigError("validation.loudness_deviation.max_lu は 0 より大きい数値で指定してください")
    return value


def list_audio_files(collection_dir: Path) -> list[Path]:
    """Return supported top-level source track paths without resolving symlinks."""
    music_dir = collection_dir / "02-Individual-music"
    if not music_dir.is_dir():
        raise ValidationError(f"ディレクトリが見つかりません: {music_dir}")
    return sorted(path for path in music_dir.iterdir() if path.is_file() and path.suffix.lower() in AUDIO_EXTS)


def collect_audio_files(collection_dir: Path) -> list[Path]:
    """Return resolved source tracks and reject an empty collection."""
    files = [path.resolve() for path in list_audio_files(collection_dir)]
    if not files:
        raise ValidationError(f"計測対象の音源がありません: {collection_dir / '02-Individual-music'}")
    return files


def evaluate_measurements(measurements: Sequence[tuple[Path, float]], max_lu: float) -> dict[str, object]:
    """Build the single-source PASS/FAIL result and median-centered target range."""
    values = [value for _, value in measurements]
    minimum = min(values)
    maximum = max(values)
    deviation = maximum - minimum
    center = statistics.median(values)
    lower = center - max_lu / 2
    upper = center + max_lu / 2
    tracks = [
        {
            "file": path.name,
            "integrated_lufs": value,
            "outlier": value < lower or value > upper,
        }
        for path, value in measurements
    ]
    return {
        "status": "PASS" if deviation <= max_lu else "FAIL",
        "max_deviation_lu": max_lu,
        "measured_deviation_lu": deviation,
        "minimum_lufs": minimum,
        "maximum_lufs": maximum,
        "target_range_lufs": [lower, upper],
        "tracks": tracks,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_loudness_receipt(
    collection_dir: Path,
    measurements: Sequence[tuple[Path, float]],
    max_lu: float,
    scan_duration_seconds: float,
) -> dict[str, object]:
    """Add immutable input identities and scan evidence to the gate result."""
    result = evaluate_measurements(measurements, max_lu)
    measured_by_name = {path.name: (path, value) for path, value in measurements}
    tracks = []
    for evaluated in result["tracks"]:
        path, _value = measured_by_name[evaluated["file"]]
        tracks.append(
            {
                **evaluated,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "collection": collection_dir.resolve().name,
        "raw_master_output": RAW_MASTER_OUTPUT_NAME,
        "full_collection_scans": 1,
        "track_count": len(tracks),
        "scan_duration_seconds": scan_duration_seconds,
        **result,
        "tracks": tracks,
    }


def write_loudness_receipt(path: Path, receipt: Mapping[str, object]) -> None:
    """Atomically write a receipt without leaving a partial validation source."""
    if not path.parent.is_dir():
        raise ValidationError(f"receipt 出力先ディレクトリが見つかりません: {path.parent}")
    payload = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValidationError(f"loudness receipt の {field} は有限数である必要があります")
    number = float(value)
    if not math.isfinite(number):
        raise ValidationError(f"loudness receipt の {field} は有限数である必要があります")
    return number


def _load_receipt(path: Path) -> Mapping[str, object]:
    if not path.is_file():
        raise ValidationError(f"loudness receipt が見つかりません: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"loudness receipt を読み込めません: {path}") from error
    if not isinstance(payload, Mapping):
        raise ValidationError("loudness receipt の root は object である必要があります")
    return payload


def _receipt_measurements(
    payload: Mapping[str, object],
    current_files: Sequence[Path],
) -> list[tuple[Path, float]]:
    raw_tracks = payload.get("tracks")
    if not isinstance(raw_tracks, list) or len(raw_tracks) != len(current_files):
        raise ValidationError("loudness receipt の対象ファイル数が現在の入力と一致しません")
    current_by_name = {path.name: path for path in current_files}
    measurements: list[tuple[Path, float]] = []
    seen: set[str] = set()
    for raw_track in raw_tracks:
        if not isinstance(raw_track, Mapping):
            raise ValidationError("loudness receipt の tracks 要素は object である必要があります")
        name = raw_track.get("file")
        if not isinstance(name, str) or name not in current_by_name or name in seen:
            raise ValidationError("loudness receipt の対象ファイルが現在の入力と一致しません")
        path = current_by_name[name]
        if raw_track.get("size_bytes") != path.stat().st_size or raw_track.get("sha256") != _sha256(path):
            raise ValidationError(f"loudness receipt の入力同定情報が一致しません: {name}")
        measurements.append((path, _finite_number(raw_track.get("integrated_lufs"), f"tracks[{name}].integrated_lufs")))
        seen.add(name)
    if seen != set(current_by_name):
        raise ValidationError("loudness receipt の対象ファイルが現在の入力と一致しません")
    return measurements


def validate_loudness_receipt(collection_dir: Path, receipt_path: Path, max_lu: float) -> dict[str, object]:
    """Validate schema, collection, inputs, threshold, measurements, and verdict."""
    collection = collection_dir.resolve()
    payload = _load_receipt(receipt_path)
    if payload.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise ValidationError("loudness receipt の schema_version が未対応です")
    if payload.get("collection") != collection.name:
        raise ValidationError("loudness receipt の collection が対象と一致しません")
    if payload.get("raw_master_output") != RAW_MASTER_OUTPUT_NAME:
        raise ValidationError("loudness receipt の raw_master_output が未対応です")
    if payload.get("full_collection_scans") != 1:
        raise ValidationError("loudness receipt は全曲走査 1 回を証明していません")
    scan_duration = _finite_number(payload.get("scan_duration_seconds"), "scan_duration_seconds")
    if scan_duration < 0:
        raise ValidationError("loudness receipt の scan_duration_seconds は 0 以上である必要があります")
    receipt_max_lu = _finite_number(payload.get("max_deviation_lu"), "max_deviation_lu")
    if receipt_max_lu != max_lu:
        raise ValidationError("loudness receipt の適用閾値が現在の設定と一致しません")
    current_files = collect_audio_files(collection)
    if payload.get("track_count") != len(current_files):
        raise ValidationError("loudness receipt の track_count が現在の入力と一致しません")
    measurements = _receipt_measurements(payload, current_files)
    expected = evaluate_measurements(measurements, max_lu)
    for field in ("status", "measured_deviation_lu", "minimum_lufs", "maximum_lufs", "target_range_lufs"):
        if payload.get(field) != expected[field]:
            raise ValidationError(f"loudness receipt の {field} が実測値からの再計算と一致しません")
    expected_tracks = expected["tracks"]
    for raw_track, expected_track in zip(payload["tracks"], expected_tracks, strict=True):
        if raw_track.get("outlier") != expected_track["outlier"]:
            raise ValidationError("loudness receipt の outlier 判定が実測値からの再計算と一致しません")
    return dict(payload)
