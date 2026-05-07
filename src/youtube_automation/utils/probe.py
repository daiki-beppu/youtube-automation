"""ffprobe ラッパー."""

from __future__ import annotations

import subprocess
from pathlib import Path


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
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
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
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return None
