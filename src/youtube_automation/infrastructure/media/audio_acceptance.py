"""FFprobe / FFmpeg による音源受入計測 adapter。"""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.media.acceptance import AudioMeasurement
from youtube_automation.infrastructure.auth.redaction import redact_sensitive_data
from youtube_automation.infrastructure.media.probe import DEFAULT_FFPROBE_TIMEOUT_SECONDS

_FFMPEG_JSON_OBJECT = re.compile(r"\{[^{}]*\}", re.DOTALL)
_FFMPEG_TIMEOUT_SECONDS = 300


def parse_loudnorm_input_i(stderr: str) -> float:
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


def _run(command: list[str], path: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise ValidationError(f"音源計測を実行できません: {path.name}") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "stderr なし"
        raise ValidationError(f"音源計測に失敗しました ({path.name}): {redact_sensitive_data(detail)}")
    return completed


def measure_integrated_lufs(path: Path) -> float:
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
    completed = _run(command, path, _FFMPEG_TIMEOUT_SECONDS)
    return parse_loudnorm_input_i(completed.stderr)


class FFmpegAudioInspector:
    def inspect(self, path: Path) -> AudioMeasurement:
        if not path.is_file() or path.is_symlink():
            raise ValidationError(f"受入対象が通常ファイルではありません: {path.name}")
        duration_command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            "--",
            str(path),
        ]
        completed = _run(duration_command, path, DEFAULT_FFPROBE_TIMEOUT_SECONDS)
        try:
            duration = float(completed.stdout.strip())
        except ValueError as error:
            raise ValidationError(f"音源 duration を取得できません: {path.name}") from error
        return AudioMeasurement(path, duration, measure_integrated_lufs(path))
