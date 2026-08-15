"""Queries for benchmark data stored in a channel repository."""

from __future__ import annotations

import json
from pathlib import Path

from youtube_automation.core.errors import ConfigError


def find_latest_benchmark_json(data_dir: Path) -> Path | None:
    """Return the newest benchmark JSON file in ``data_dir``."""
    files = sorted(data_dir.glob("benchmark_*.json"), reverse=True)
    return files[0] if files else None


def load_benchmark_videos(
    data_dir: Path,
    min_views: int = 10000,
    require_thumbnail: bool = False,
    competitor_slug: str | None = None,
) -> list[dict]:
    """Load and filter videos from the newest benchmark JSON."""
    benchmark_path = find_latest_benchmark_json(data_dir)
    if not benchmark_path:
        raise ConfigError(
            f"ベンチマーク JSON が見つかりません ({data_dir})。"
            "先に `/channel-research --benchmark`（uv run yt-benchmark-collect）を実行して"
            "競合データを収集してください。"
        )
    with benchmark_path.open(encoding="utf-8") as benchmark_file:
        data = json.load(benchmark_file)
    targets: list[dict] = []
    seen_ids: set[str] = set()
    for channel in data.get("channels", []):
        competitor_name = channel.get("name", "Unknown")
        current_slug = channel.get("slug", "unknown")
        if competitor_slug and current_slug != competitor_slug:
            continue
        for video in channel.get("videos", []):
            video_id = video.get("video_id", "")
            if video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            views = int(video.get("views", 0))
            thumbnail_url = video.get("thumbnail_url", "")
            if views < min_views or (require_thumbnail and not thumbnail_url):
                continue
            targets.append(
                {
                    "video_id": video_id,
                    "title": video.get("title", ""),
                    "views": views,
                    "channel_name": competitor_name,
                    "channel_slug": current_slug,
                    "published_at": video.get("published_at", ""),
                    "duration_iso": video.get("duration_iso", ""),
                    "thumbnail_url": thumbnail_url,
                }
            )
    if not targets:
        thumb_note = "（かつサムネイル URL あり）" if require_thumbnail else ""
        raise ConfigError(
            f"ベンチマーク JSON に {min_views:,} 再生以上の動画{thumb_note}が 1 件もありません "
            f"({benchmark_path.name})。min_views しきい値を見直すか、"
            "`/channel-research --benchmark`（uv run yt-benchmark-collect）で最新データを再収集してください。"
        )
    targets.sort(key=lambda item: item["views"], reverse=True)
    return targets
