"""ffprobe ラッパー."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

DEFAULT_FFPROBE_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class VideoProbe:
    duration_seconds: float
    width: int
    height: int
    codec: str


def probe_duration(path: Path) -> float | None:
    """ffprobe で動画/音声ファイルの再生秒数を取得する。失敗時は None."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                "--",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=DEFAULT_FFPROBE_TIMEOUT_SECONDS,
        )
        value = float(result.stdout.strip())
        return value if isfinite(value) else None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        return None


def probe_bitrate(path: Path) -> float | None:
    """ffprobe で動画/音声ファイル全体のビットレート (bps) を取得する。失敗時は None.

    `format=bit_rate` を参照するため、container 全体の平均ビットレートが返る。
    Mbps 換算は呼び出し側の責務。
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=bit_rate",
                "-of",
                "csv=p=0",
                "--",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=DEFAULT_FFPROBE_TIMEOUT_SECONDS,
        )
        value = float(result.stdout.strip())
        return value if isfinite(value) else None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        return None


def probe_video(path: Path) -> VideoProbe | None:
    """動画の表示用probe値を1回のffprobeで取得する。"""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "format=duration:stream=codec_name,width,height",
                "-of",
                "json",
                "--",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=DEFAULT_FFPROBE_TIMEOUT_SECONDS,
        )
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            return None
        streams = payload.get("streams")
        format_value = payload.get("format")
        if not isinstance(streams, list) or len(streams) != 1 or not isinstance(format_value, dict):
            return None
        stream = streams[0]
        if not isinstance(stream, dict):
            return None
        duration = float(format_value.get("duration"))
        width = stream.get("width")
        height = stream.get("height")
        codec = stream.get("codec_name")
        if (
            not isfinite(duration)
            or duration <= 0
            or isinstance(width, bool)
            or not isinstance(width, int)
            or width <= 0
            or isinstance(height, bool)
            or not isinstance(height, int)
            or height <= 0
            or not isinstance(codec, str)
            or not codec
        ):
            return None
        return VideoProbe(duration, width, height, codec)
    except (
        json.JSONDecodeError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        TypeError,
        ValueError,
        FileNotFoundError,
    ):
        return None
