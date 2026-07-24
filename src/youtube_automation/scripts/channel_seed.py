"""yt-channel-seed CLI."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path

from youtube_automation.domains.youtube.channel_seed import (
    SeedChannel,
    fetch_channel_seed,
    merge_benchmark_channel,
    to_benchmark_entry,
)
from youtube_automation.infrastructure.auth.youtube import YouTubeOAuthHandler
from youtube_automation.infrastructure.errors import AutomationError, ConfigError
from youtube_automation.infrastructure.google.youtube import YouTubeClients

ANALYTICS_PATH = Path("config") / "channel" / "analytics.json"
DEFAULT_RECENT_COUNT = 10
PLACEHOLDER_RELATIONSHIPS = {"", "seed", "default", "unknown", "none", "n/a", "未設定", "なし"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-channel-seed",
        description="ベンチマーク seed チャンネルを取得し、analytics.json の benchmark.channels に反映する。",
    )
    parser.add_argument("url", help="YouTube channel URL / handle / channel ID")
    parser.add_argument("--target", help="チャンネルリポジトリのルートディレクトリ")
    parser.add_argument(
        "--relationship",
        help="benchmark.channels[].relationship。analytics.json へ書き込む場合は必須。",
    )
    parser.add_argument("--recent", type=int, default=DEFAULT_RECENT_COUNT, help="取得する直近動画タイトル数")
    parser.add_argument(
        "--no-write-benchmark",
        dest="write_benchmark",
        action="store_false",
        help="analytics.json への反映を行わない",
    )
    parser.add_argument("--json", action="store_true", help="取得結果を JSON で出力する")
    parser.set_defaults(write_benchmark=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        clients = YouTubeClients(
            full_handler=YouTubeOAuthHandler(),
            readonly_handler=YouTubeOAuthHandler.create_readonly(),
        )
        seed = fetch_channel_seed(clients.youtube_readonly, args.url, recent=args.recent)
        if args.write_benchmark:
            _write_benchmark_entry(_resolve_target(args.target), seed, args.relationship)
        _print_seed(seed, as_json=args.json)
    except AutomationError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1
    return 0


def _resolve_target(target: str | None) -> Path:
    if target is None:
        return Path.cwd().resolve()
    path = Path(target).resolve()
    if not path.is_dir():
        raise ConfigError(f"--target で指定されたディレクトリが存在しません: {path}")
    return path


def _write_benchmark_entry(target: Path, seed: SeedChannel, relationship: str | None) -> None:
    relationship_value = (relationship or "").strip()
    if relationship_value.lower() in PLACEHOLDER_RELATIONSHIPS:
        raise ConfigError("--relationship には TTP で転写する具体的な関係性メモを指定してください")

    path = target / ANALYTICS_PATH
    if not path.is_file():
        raise ConfigError(f"analytics.json が存在しません: {path}")
    analytics = json.loads(path.read_text(encoding="utf-8"))
    entry = to_benchmark_entry(seed, relationship=relationship_value)
    merged = merge_benchmark_channel(analytics, entry)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _print_seed(seed: SeedChannel, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(_seed_to_dict(seed), ensure_ascii=False, indent=2))
        return
    print(f"Channel: {seed.name}")
    print(f"ID: {seed.channel_id}")
    print(f"Handle: {seed.handle}")
    print(f"Subscribers: {seed.subscribers:,}")
    print(f"Videos: {seed.total_videos:,}")
    print("Recent titles:")
    for title in seed.recent_titles:
        print(f"- {title}")


def _seed_to_dict(seed: SeedChannel) -> dict:
    return {
        "channel_id": seed.channel_id,
        "handle": seed.handle,
        "name": seed.name,
        "subscribers": seed.subscribers,
        "total_videos": seed.total_videos,
        "uploads_playlist_id": seed.uploads_playlist_id,
        "recent_titles": list(seed.recent_titles),
    }


if __name__ == "__main__":
    raise SystemExit(main())
