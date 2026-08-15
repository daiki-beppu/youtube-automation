#!/usr/bin/env python3
"""Measure per-track integrated LUFS and enforce a collection spread limit."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ConfigError, ValidationError
from youtube_automation.domains.media.loudness_receipt import (
    build_loudness_receipt,
    collect_audio_files,
    resolve_max_deviation_lu,
    validate_loudness_receipt,
    write_loudness_receipt,
)

_FFMPEG_JSON_OBJECT = re.compile(r"\{[^{}]*\}", re.DOTALL)


def load_max_deviation_lu() -> float:
    """Resolve the deviation threshold from the merged masterup skill config."""
    return resolve_max_deviation_lu(load_skill_config("masterup"))


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
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--receipt", type=Path, help="write a machine-readable receipt after measuring")
    modes.add_argument("--validate-receipt", type=Path, help="validate a receipt without running FFmpeg")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        max_lu = load_max_deviation_lu()
        collection = args.collection.resolve()
        if args.validate_receipt is not None:
            result = validate_loudness_receipt(collection, args.validate_receipt.resolve(), max_lu)
        else:
            files = collect_audio_files(collection)
            started = time.monotonic()
            measurements = [(path, measure_integrated_lufs(path)) for path in files]
            elapsed = time.monotonic() - started
            result = build_loudness_receipt(collection, measurements, max_lu, elapsed)
            if args.receipt is not None:
                write_loudness_receipt(args.receipt.resolve(), result)
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
