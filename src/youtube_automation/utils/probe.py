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
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
        return None
