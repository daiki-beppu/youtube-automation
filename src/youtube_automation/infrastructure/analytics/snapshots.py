"""Locate persisted analytics snapshots in chronological filename order."""

import json
from pathlib import Path

from youtube_automation.core.errors import ConfigError


def find_analytics_snapshots(channel_dir: Path) -> list[Path]:
    """Return available snapshots, rejecting an uncollected channel consistently."""
    candidates = sorted((channel_dir / "data").glob("analytics_data_*.json"))
    if not candidates:
        raise ConfigError("analytics_data_*.json が見つかりません。先に `yt-analytics` を実行してください。")
    return candidates


def load_latest_analytics_snapshot(channel_dir: Path) -> dict:
    """Read only the newest snapshot; older malformed files do not affect this view."""
    path = find_analytics_snapshots(channel_dir)[-1]
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)
