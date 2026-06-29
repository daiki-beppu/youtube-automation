#!/usr/bin/env python3
"""Terraform external data source for streaming source video preflight."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_KEYFRAME_INTERVAL_SEC = 4.0
MIN_BITRATE_BY_HEIGHT_KBPS = (
    (1080, 4500),
    (720, 2500),
)
DEFAULT_MIN_BITRATE_KBPS = 1500


def _result(
    *,
    ok: bool,
    status: str,
    message: str,
    profile_ok: bool = True,
    profile_message: str = "",
    **extra: object,
) -> dict[str, str]:
    data: dict[str, str] = {
        "ok": str(ok).lower(),
        "status": status,
        "message": message,
        "profile_ok": str(profile_ok).lower(),
        "profile_message": profile_message or message,
    }
    data.update({key: str(value) for key, value in extra.items()})
    return data


def _run_ffprobe(args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout or "{}")


def _video_metadata(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    data = _run_ffprobe(
        [
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,profile,width,height,bit_rate",
            "-show_entries",
            "format=bit_rate,duration",
            "-of",
            "json",
            "--",
            str(path),
        ]
    )
    streams = data.get("streams")
    stream = streams[0] if isinstance(streams, list) and streams else {}
    format_info = data.get("format") if isinstance(data.get("format"), dict) else {}
    return stream if isinstance(stream, dict) else {}, format_info


def _keyframe_times(path: Path) -> list[float]:
    data = _run_ffprobe(
        [
            "-select_streams",
            "v:0",
            "-skip_frame",
            "nokey",
            "-show_entries",
            "frame=best_effort_timestamp_time,pkt_pts_time,pts_time",
            "-of",
            "json",
            "--",
            str(path),
        ]
    )
    frames = data.get("frames")
    if not isinstance(frames, list):
        return []

    times: list[float] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        raw = frame.get("best_effort_timestamp_time") or frame.get("pkt_pts_time") or frame.get("pts_time")
        try:
            times.append(float(raw))
        except (TypeError, ValueError):
            continue
    return sorted(set(times))


def _max_interval(times: list[float]) -> float | None:
    if len(times) < 2:
        return None
    return max(b - a for a, b in zip(times, times[1:], strict=False))


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _required_bitrate_kbps(height: int | None) -> int:
    if height is None:
        return DEFAULT_MIN_BITRATE_KBPS
    for min_height, bitrate in MIN_BITRATE_BY_HEIGHT_KBPS:
        if height >= min_height:
            return bitrate
    return DEFAULT_MIN_BITRATE_KBPS


def check_video(path: Path) -> dict[str, str]:
    if shutil.which("ffprobe") is None:
        return _result(
            ok=True,
            status="skipped",
            message="ffprobe not found; source video preflight skipped.",
        )
    if not path.is_file():
        return _result(ok=False, status="failed", message=f"source video does not exist: {path}")

    try:
        stream, format_info = _video_metadata(path)
        keyframes = _keyframe_times(path)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        return _result(ok=False, status="failed", message=f"ffprobe failed for source video: {exc}")

    height = _int_or_none(stream.get("height"))
    width = _int_or_none(stream.get("width"))
    bitrate_bps = _int_or_none(stream.get("bit_rate")) or _int_or_none(format_info.get("bit_rate"))
    bitrate_kbps = round(bitrate_bps / 1000) if bitrate_bps is not None else None
    required_bitrate_kbps = _required_bitrate_kbps(height)
    max_keyframe_interval = _max_interval(keyframes)

    failures: list[str] = []
    if max_keyframe_interval is not None and max_keyframe_interval > MAX_KEYFRAME_INTERVAL_SEC:
        failures.append(f"keyframe interval {max_keyframe_interval:.2f}s exceeds {MAX_KEYFRAME_INTERVAL_SEC:.0f}s")
    if bitrate_kbps is None:
        failures.append("video bitrate is unavailable")
    elif bitrate_kbps < required_bitrate_kbps:
        failures.append(f"video bitrate {bitrate_kbps} Kbps is below {required_bitrate_kbps} Kbps")

    codec = str(stream.get("codec_name") or "")
    profile = str(stream.get("profile") or "")
    profile_ok = codec == "h264" and "high" in profile.lower()
    profile_message = (
        "source video uses H.264 High profile."
        if profile_ok
        else f"source video profile is {codec or 'unknown'} / {profile or 'unknown'}; H.264 High is recommended."
    )

    interval_summary = f"{max_keyframe_interval:.2f}s" if max_keyframe_interval is not None else "unknown"
    summary = (
        f"source video {width or '?'}x{height or '?'}; "
        f"bitrate={bitrate_kbps or 'unknown'} Kbps; "
        f"max_keyframe_interval={interval_summary}"
    )
    if failures:
        return _result(
            ok=False,
            status="failed",
            message="; ".join(failures),
            profile_ok=profile_ok,
            profile_message=profile_message,
            width=width or "",
            height=height or "",
            bitrate_kbps=bitrate_kbps or "",
            required_bitrate_kbps=required_bitrate_kbps,
            max_keyframe_interval_sec=(f"{max_keyframe_interval:.3f}" if max_keyframe_interval is not None else ""),
        )
    return _result(
        ok=True,
        status="ok",
        message=summary,
        profile_ok=profile_ok,
        profile_message=profile_message,
        width=width or "",
        height=height or "",
        bitrate_kbps=bitrate_kbps or "",
        required_bitrate_kbps=required_bitrate_kbps,
        max_keyframe_interval_sec=f"{max_keyframe_interval:.3f}" if max_keyframe_interval is not None else "",
    )


def main() -> int:
    query = json.load(sys.stdin)
    video_path = query.get("video_path")
    if not isinstance(video_path, str) or not video_path:
        json.dump(_result(ok=False, status="failed", message="video_path is required."), sys.stdout)
        return 0
    json.dump(check_video(Path(video_path).expanduser()), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
