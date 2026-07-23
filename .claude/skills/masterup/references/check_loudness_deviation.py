#!/usr/bin/env python3
"""Measure per-track integrated LUFS and enforce a collection spread limit."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import statistics
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from youtube_automation.domains.media.audio_formats import AUDIO_EXTS
from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.skill_config import load_skill_config

_DEFAULT_MAX_DEVIATION_LU = 2.0
_FFMPEG_JSON_OBJECT = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _as_mapping(value: object, context: str) -> Mapping[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"skill-config の {context} は mapping である必要があります: {value!r}")
    return value


def load_max_deviation_lu() -> float:
    """Resolve the deviation threshold from the merged masterup skill config."""
    config = load_skill_config("masterup")
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


def collect_audio_files(collection_dir: Path) -> list[Path]:
    """Return supported top-level source tracks in deterministic order."""
    music_dir = collection_dir / "02-Individual-music"
    if not music_dir.is_dir():
        raise ValidationError(f"ディレクトリが見つかりません: {music_dir}")
    files = sorted(
        path.resolve() for path in music_dir.iterdir() if path.is_file() and path.suffix.lower() in AUDIO_EXTS
    )
    if not files:
        raise ValidationError(f"計測対象の音源がありません: {music_dir}")
    return files


def parse_loudnorm_input_i(stderr: str) -> float:
    """Extract the last finite input_i value from FFmpeg loudnorm JSON output."""
    for match in reversed(list(_FFMPEG_JSON_OBJECT.finditer(stderr))):
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if "input_i" not in payload:
            continue
        try:
            value = float(payload["input_i"])
        except (TypeError, ValueError) as error:
            raise ValidationError(f"FFmpeg input_i を数値へ変換できません: {payload['input_i']!r}") from error
        if not math.isfinite(value):
            raise ValidationError(f"FFmpeg input_i が有限値ではありません: {payload['input_i']!r}")
        return value
    raise ValidationError("FFmpeg loudnorm 出力に input_i JSON がありません")


def measure_integrated_lufs(path: Path) -> float:
    """Measure one track with FFmpeg's EBU R128 loudnorm filter."""
    if shutil.which("ffmpeg") is None:
        raise ValidationError("ffmpeg が PATH にありません。/setup を先に実行してください")
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        "loudnorm=I=-14:LRA=11:TP=-1.5:print_format=json",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "stderr なし"
        raise ValidationError(f"FFmpeg 計測失敗 ({path.name}): {detail}")
    return parse_loudnorm_input_i(completed.stderr)


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


def _print_human(result: Mapping[str, object]) -> None:
    lower, upper = result["target_range_lufs"]
    print(
        f"{result['status']}: measured deviation={result['measured_deviation_lu']:.2f} LU "
        f"(limit={result['max_deviation_lu']:.2f} LU)"
    )
    print(f"target range (median ± limit/2): {lower:.2f} .. {upper:.2f} LUFS")
    for track in result["tracks"]:
        marker = "OUTLIER" if track["outlier"] else "OK"
        print(f"- [{marker}] {track['file']}: {track['integrated_lufs']:.2f} LUFS")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path, help="collection directory")
    parser.add_argument("--json", action="store_true", help="emit the result as JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        max_lu = load_max_deviation_lu()
        files = collect_audio_files(args.collection.resolve())
        measurements = [(path, measure_integrated_lufs(path)) for path in files]
        result = evaluate_measurements(measurements, max_lu)
    except (ConfigError, ValidationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
