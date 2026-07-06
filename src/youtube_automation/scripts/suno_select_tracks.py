#!/usr/bin/env python3
"""CLI wrapper for Suno clip selection before masterup."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping

from youtube_automation.utils.collection_paths import resolve_collection_dir
from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.suno_track_selection import select_suno_tracks


def _configured_min_song_sec(cfg: Mapping[str, object]) -> float | None:
    pair_selection = cfg.get("pair_selection")
    if not isinstance(pair_selection, Mapping):
        return 45.0
    value = pair_selection.get("min_song_sec", 45)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Suno clips を歌詞-aware に選別し、尺外音源を除外する")
    parser.add_argument("collection", nargs="?", help="コレクションディレクトリ (省略時は CWD)")
    parser.add_argument("--dry-run", action="store_true", help="ファイル移動せず plan と log を stdout 表示")
    parser.add_argument(
        "--allow-best-effort-over-max",
        action="store_true",
        help="全候補が max_song_sec 超過した prompt は最短候補を警告付きで例外採用する",
    )
    args = parser.parse_args()

    try:
        collection_dir = resolve_collection_dir(args.collection)
        cfg = load_skill_config("masterup")
        result = select_suno_tracks(
            collection_dir,
            cfg,
            dry_run=args.dry_run,
            allow_best_effort_over_max=args.allow_best_effort_over_max,
        )
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    min_song_sec = _configured_min_song_sec(cfg)
    dropped_under_min = [
        candidate for candidate in result.dropped if min_song_sec is not None and candidate.duration < min_song_sec
    ]
    print(
        "[yt-suno-select-tracks] "
        f"kept={len(result.kept)} stocked={len(result.stocked)} "
        f"deleted={len(result.deleted)} dropped_duration={len(result.dropped)} "
        f"dropped_under_min={len(dropped_under_min)} "
        f"exceptions_over_limit={len(result.exceptions_over_limit)} "
        f"log={result.log_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
