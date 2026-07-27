"""Provider-neutral benchmark video policies."""

from __future__ import annotations

import re

LIVE_DURATION_ISO = "P0D"
TTP_VIDEO_ANALYZE_TOP_N = 5


def is_short_benchmark_duration(duration_iso: str) -> bool:
    """Return whether an ISO duration is shorter than five minutes."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_iso)
    if not match:
        return False
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    return hours == 0 and minutes < 5


def is_short_benchmark_video(video: dict) -> bool:
    """Return whether a benchmark entry is a short video."""
    return is_short_benchmark_duration(str(video.get("duration_iso") or ""))


def is_live_benchmark_video(video: dict) -> bool:
    """Return whether a benchmark entry is an active/live stream."""
    return str(video.get("duration_iso") or "") == LIVE_DURATION_ISO


def select_top_vod_benchmark_videos(videos: list[dict], top: int) -> tuple[list[dict], list[dict]]:
    """Select analyzable VODs while excluding live streams."""
    selected: list[dict] = []
    skipped_live: list[dict] = []
    for video in videos:
        if len(selected) >= top:
            break
        if is_live_benchmark_video(video):
            skipped_live.append(video)
            continue
        selected.append(video)
    return selected, skipped_live


__all__ = [
    "LIVE_DURATION_ISO",
    "TTP_VIDEO_ANALYZE_TOP_N",
    "is_live_benchmark_video",
    "is_short_benchmark_duration",
    "is_short_benchmark_video",
    "select_top_vod_benchmark_videos",
]
