"""Truth Eye が読む benchmark 母集団の横断 read adapter。"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

from youtube_automation.core.errors import ConfigError
from youtube_automation.domains.analytics.benchmark import find_latest_benchmark_json
from youtube_automation.domains.analytics.truth_eye import read_training_record
from youtube_automation.infrastructure.analytics.channel_registry import (
    DEFAULT_CHANNEL_REGISTRY,
    load_channel_registry,
)


def load_truth_eye_population(channel_dir: Path, *, freshness_days: int = 3) -> tuple[list[dict], set[str], list[str]]:
    """自チャンネルと競合 ID を共有する兄弟から走査プールを読む。"""
    own = channel_dir.resolve()
    own_config = _benchmark_channels(own)
    if not own_config:
        raise ConfigError("benchmark.channels が空です。channel-research --benchmark を実行してください")
    own_ids = {item["id"] for item in own_config}
    repositories = [(own, "self")]
    for sibling in _first_party_repositories(own):
        if sibling == own:
            continue
        sibling_config = _benchmark_channels(sibling, required=False)
        if own_ids & {item["id"] for item in sibling_config}:
            repositories.append((sibling, sibling.name))

    used_ids, sessions = _training_history(own)
    competitors: list[dict] = []
    seen_ids: set[str] = set()
    warnings: list[str] = []
    for repository, source in repositories:
        benchmark_path = find_latest_benchmark_json(repository / "data")
        if benchmark_path is None:
            raise ConfigError(
                f"{source} ({repository}) に benchmark JSON がありません。"
                "channel-research --benchmark を実行してください"
            )
        age = (date.today() - _benchmark_date(benchmark_path)).days
        if age > freshness_days:
            warnings.append(
                f"{source} の benchmark JSON が {age} 日前のものです。channel-research --benchmark で更新できます"
            )
        payload = _read_json(benchmark_path)
        for channel in payload.get("channels", []):
            competitor_id = channel.get("channel_id") or channel.get("id")
            if not isinstance(competitor_id, str) or competitor_id in seen_ids:
                continue
            scan = channel.get("upload_scan", {}).get("videos", [])
            if any("video_id" not in video for video in scan):
                raise ConfigError(
                    f"{source} の走査記録が旧 shape です。対象リポジトリ {repository} で "
                    "uv run yt-benchmark-collect --force -y を実行してください"
                )
            seen_ids.add(competitor_id)
            slug = str(channel.get("slug", "unknown"))
            competitors.append(
                {
                    "id": competitor_id,
                    "slug": slug,
                    "name": str(channel.get("name", slug)),
                    "source": source,
                    "videos": scan,
                    "thumbnails_dir": repository / "docs" / "benchmarks" / "thumbnails",
                    "past_sessions": sessions.get(slug, 0),
                }
            )
    return competitors, used_ids, warnings


def _first_party_repositories(channel_dir: Path) -> list[Path]:
    if DEFAULT_CHANNEL_REGISTRY.is_file():
        return [path.resolve() for path in load_channel_registry(DEFAULT_CHANNEL_REGISTRY)]
    return [channel_dir.resolve()]


def _benchmark_channels(repository: Path, *, required: bool = True) -> list[dict]:
    path = repository / "config" / "channel" / "analytics.json"
    if not path.is_file():
        if required:
            raise ConfigError(
                f"{repository} に analytics.json がありません。channel-research --benchmark を実行してください"
            )
        return []
    payload = _read_json(path)
    channels = payload.get("benchmark", {}).get("channels", [])
    if not isinstance(channels, list):
        return []
    for index, channel in enumerate(channels):
        if not isinstance(channel, dict):
            raise ConfigError(f"benchmark.channels[{index}] が object ではありません: {path}")
        competitor_id = channel.get("id")
        if not isinstance(competitor_id, str) or not competitor_id:
            raise ConfigError(f"benchmark.channels[{index}].id が不正です: {path}")
    return channels


def _training_history(repository: Path) -> tuple[set[str], dict[str, int]]:
    used: set[str] = set()
    sessions: dict[str, int] = {}
    training = repository / "docs" / "benchmarks" / "training"
    for path in sorted(training.glob("*.md")) if training.is_dir() else []:
        if path.name.endswith(".sealed.md"):
            continue
        record = read_training_record(path)
        channel = str(record.metadata.get("channel", ""))
        sessions[channel] = sessions.get(channel, 0) + 1
        pair = record.metadata.get("pair", {})
        for side in ("winner", "loser"):
            video_id = pair.get(side, {}).get("video_id") if isinstance(pair, dict) else None
            if isinstance(video_id, str):
                used.add(video_id)
    return used, sessions


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"JSON を読めません: {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ConfigError(f"JSON は object である必要があります: {path}")
    return payload


def _benchmark_date(path: Path) -> date:
    match = re.search(r"benchmark_(\d{8})", path.name)
    if match:
        return datetime.strptime(match.group(1), "%Y%m%d").date()
    return datetime.fromtimestamp(path.stat().st_mtime).date()
