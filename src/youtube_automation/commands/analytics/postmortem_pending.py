#!/usr/bin/env python3
"""List live collections whose postmortem is ready to be written."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TypedDict

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.configuration import channel_dir as _channel_dir
from youtube_automation.core.errors import ConfigError
from youtube_automation.domains.uploads.collection import TrackingStore

UPLOAD_TRACKING_MISSING = "upload_tracking_missing"
VIDEO_ID_MISSING = "video_id_missing"
ANALYTICS_DATA_MISSING = "analytics_data_missing"
VIDEO_NOT_IN_ANALYTICS = "video_not_in_analytics"


class PendingEntry(TypedDict):
    collection: str
    video_id: str
    postmortem_path: str


class UnanalyzableEntry(TypedDict):
    collection: str
    video_id: str | None
    reason: str


class PostmortemReport(TypedDict):
    schema_version: int
    analytics_data_path: str | None
    pending: list[PendingEntry]
    unanalyzable: list[UnanalyzableEntry]


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser without resolving channel configuration."""
    parser = argparse.ArgumentParser(description="未作成の postmortem と分析可否を一覧表示します")
    parser.add_argument("--json", action="store_true", help="機械可読な JSON で出力")
    return parser


def _latest_analytics(channel_root: Path) -> tuple[Path | None, set[str]]:
    candidates = sorted((channel_root / "data").glob("analytics_data_*.json"))
    if not candidates:
        return None, set()

    latest = candidates[-1]
    try:
        payload: object = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"analytics データを読み込めません: {latest}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ConfigError(f"analytics データのルートは object である必要があります: {latest}")
    video_analytics = payload.get("video_analytics")
    if not isinstance(video_analytics, dict):
        raise ConfigError(f"video_analytics は object である必要があります: {latest}")
    if not all(isinstance(video_id, str) for video_id in video_analytics):
        raise ConfigError(f"video_analytics のキーは string である必要があります: {latest}")
    return latest, set(video_analytics)


def _tracking_video_id(store: TrackingStore, collection: Path) -> tuple[str | None, str | None]:
    tracking_path = store.tracking_path(collection)
    if not tracking_path.is_file():
        return None, UPLOAD_TRACKING_MISSING

    try:
        tracking: object = store.read(collection)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"upload tracking を読み込めません: {tracking_path}: {exc}") from exc

    if not isinstance(tracking, dict):
        raise ConfigError(f"upload tracking のルートは object である必要があります: {tracking_path}")
    complete = tracking.get("complete_collection")
    video_id = complete.get("video_id") if isinstance(complete, dict) else None
    if not isinstance(video_id, str) or not video_id.strip():
        return None, VIDEO_ID_MISSING
    return video_id.strip(), None


def build_report(channel_root: Path) -> PostmortemReport:
    """Build a read-only report from upload tracking and the latest analytics snapshot."""
    analytics_path, analytics_video_ids = _latest_analytics(channel_root)
    live_root = channel_root / "collections" / "live"
    store = TrackingStore(channel_root / "collections", {})
    pending: list[PendingEntry] = []
    unanalyzable: list[UnanalyzableEntry] = []

    collections = sorted(path for path in live_root.iterdir() if path.is_dir()) if live_root.is_dir() else []
    for collection in collections:
        postmortem = collection / "20-documentation" / "postmortem.md"
        if postmortem.is_file():
            continue

        video_id, tracking_reason = _tracking_video_id(store, collection)
        reason = tracking_reason
        if reason is None and analytics_path is None:
            reason = ANALYTICS_DATA_MISSING
        elif reason is None and video_id not in analytics_video_ids:
            reason = VIDEO_NOT_IN_ANALYTICS

        if reason is not None:
            unanalyzable.append({"collection": collection.name, "video_id": video_id, "reason": reason})
            continue

        assert video_id is not None
        pending.append(
            {
                "collection": collection.name,
                "video_id": video_id,
                "postmortem_path": postmortem.relative_to(channel_root).as_posix(),
            }
        )

    return {
        "schema_version": 1,
        "analytics_data_path": (
            analytics_path.relative_to(channel_root).as_posix() if analytics_path is not None else None
        ),
        "pending": pending,
        "unanalyzable": unanalyzable,
    }


def _print_human(report: PostmortemReport) -> None:
    pending = report["pending"]
    unanalyzable = report["unanalyzable"]
    print(f"pending: {len(pending)}")
    for item in pending:
        print(f"  - {item['collection']} ({item['video_id']})")
    print(f"unanalyzable: {len(unanalyzable)}")
    for item in unanalyzable:
        print(f"  - {item['collection']}: {item['reason']}")


def run(args: argparse.Namespace) -> int:
    report = build_report(_channel_dir())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv)


if __name__ == "__main__":
    sys.exit(main())
