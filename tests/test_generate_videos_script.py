"""`generate_videos.sh` の loop 正規化分岐を固定するテスト."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / ".claude" / "skills" / "videoup" / "references" / "generate_videos.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _create_collection(tmp_path: Path) -> Path:
    collection = tmp_path / "001-test-ambient-collection"
    master_dir = collection / "01-master"
    assets_dir = collection / "10-assets"
    master_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)
    (master_dir / "master-mix.wav").write_bytes(b"fake-audio")
    (assets_dir / "main.jpg").write_bytes(b"fake-image")
    (assets_dir / "loop.mp4").write_bytes(b"fake-video")
    return collection


def _create_stub_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "ffprobe",
        """#!/bin/bash
set -eu
args="$*"
if [[ "$args" == *"format=duration"* ]]; then
    printf '1.00\\n'
    exit 0
fi
if [[ "$args" == *"stream=width,height,pix_fmt,r_frame_rate"* ]]; then
    printf '%s\\n' "${FFPROBE_STREAM_OUTPUT}"
    exit 0
fi
if [[ "$args" == *"stream=bit_rate"* ]]; then
    printf '%s\\n' "${FFPROBE_STREAM_BITRATE_OUTPUT:-}"
    exit 0
fi
if [[ "$args" == *"format=bit_rate"* ]]; then
    printf '%s\\n' "${FFPROBE_FORMAT_BITRATE_OUTPUT:-}"
    exit 0
fi
exit 0
""",
    )
    _write_executable(
        bin_dir / "ffmpeg",
        """#!/bin/bash
set -eu
if [[ "$*" == *"-encoders"* ]]; then
    printf ' A..... aac \\n'
    exit 0
fi

if [[ -n "${FFMPEG_LOG:-}" ]]; then
    printf '%s\\n' "$*" >> "${FFMPEG_LOG}"
fi

progress_path=""
prev=""
for arg in "$@"; do
    if [[ "$prev" == "-progress" ]]; then
        progress_path="$arg"
    fi
    prev="$arg"
done

if [[ -n "$progress_path" ]]; then
    printf 'out_time_us=1000000\\n' > "$progress_path"
fi

output_path="${!#}"
mkdir -p "$(dirname "$output_path")"
printf 'stub-output' > "$output_path"
""",
    )
    return bin_dir


def _run_generate_videos(
    tmp_path: Path,
    stream_output: str,
    *,
    stream_bitrate_output: str = "",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    collection = _create_collection(tmp_path)
    bin_dir = _create_stub_bin(tmp_path)
    ffmpeg_log = tmp_path / "ffmpeg.log"
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FFPROBE_STREAM_OUTPUT"] = stream_output
    env["FFPROBE_STREAM_BITRATE_OUTPUT"] = stream_bitrate_output
    env["FFMPEG_LOG"] = str(ffmpeg_log)
    result = subprocess.run(
        ["bash", str(_SCRIPT_PATH), str(collection)],
        capture_output=True,
        text=True,
        env=env,
        cwd=_REPO_ROOT,
    )
    return result, ffmpeg_log


def test_24fps_loop_skips_normalization(tmp_path: Path) -> None:
    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="5000000",
    )

    assert result.returncode == 0, result.stderr
    commands = ffmpeg_log.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 1
    assert "loop_normalized.mp4" not in commands[0]
    assert "10-assets/loop.mp4" in commands[0]


def test_high_bitrate_24fps_loop_runs_normalization(tmp_path: Path) -> None:
    result, ffmpeg_log = _run_generate_videos(
        tmp_path,
        "1920,1080,yuv420p,24/1",
        stream_bitrate_output="15650000",
    )

    assert result.returncode == 0, result.stderr
    commands = ffmpeg_log.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 2
    assert "loop_normalized.mp4" in commands[0]
    assert " -crf 22 " in f" {commands[0]} "
    assert " -maxrate 6000k " in f" {commands[0]} "
    assert " -bufsize 12000k " in f" {commands[0]} "
    assert "10-assets/loop_normalized.mp4" in commands[1]


def test_non_24fps_loop_runs_normalization_with_fixed_24fps(tmp_path: Path) -> None:
    result, ffmpeg_log = _run_generate_videos(tmp_path, "1920,1080,yuv420p,30/1")

    assert result.returncode == 0, result.stderr
    commands = ffmpeg_log.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 2
    assert "loop_normalized.mp4" in commands[0]
    assert " -r 24 " in f" {commands[0]} "
    assert "10-assets/loop_normalized.mp4" in commands[1]
