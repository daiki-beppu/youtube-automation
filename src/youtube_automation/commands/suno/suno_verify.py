#!/usr/bin/env python3
"""Validate Suno prompt and lyric artifacts before browser generation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from youtube_automation.configuration import channel_dir
from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ConfigError, ValidationError
from youtube_automation.domains.suno.config import infer_suno_mode, resolve_suno_config
from youtube_automation.domains.suno.downloaded.validation import verify_suno_collection
from youtube_automation.infrastructure.media.collection_paths import resolve_collection_dir


def _resolve_collection_argument(collection: str | None) -> Path:
    """明示パスを維持し、bare name だけを channel collections から解決する."""
    if collection is None:
        return resolve_collection_dir(None)

    explicit = Path(collection)
    if explicit.is_absolute() or explicit.exists() or "/" in collection or "\\" in collection:
        return resolve_collection_dir(collection)

    collections_root = channel_dir() / "collections"
    for stage in ("planning", "live"):
        candidate = collections_root / stage / collection
        if candidate.is_dir():
            return candidate.resolve()

    raise ValidationError(
        f"コレクション '{collection}' が collections/planning/ にも collections/live/ にも見つかりません"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate suno-prompts.json and suno-lyrics.json artifacts")
    parser.add_argument("collection", nargs="?", help="collection directory (default: CWD)")
    args = parser.parse_args()

    try:
        collection_dir = _resolve_collection_argument(args.collection)
        suno_cfg = resolve_suno_config(load_skill_config("suno"))
        issues, summary = verify_suno_collection(collection_dir, suno_cfg, infer_suno_mode)
    except (ConfigError, ValidationError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 1

    if issues:
        print(f"NG yt-suno-verify found {len(issues)} issue(s)")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print(f"OK yt-suno-verify {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
