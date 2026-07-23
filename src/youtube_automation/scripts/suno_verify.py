#!/usr/bin/env python3
"""Validate Suno prompt and lyric artifacts before browser generation."""

from __future__ import annotations

import argparse
import sys

from youtube_automation.domains.suno.config import infer_suno_mode, resolve_suno_config
from youtube_automation.domains.suno.downloaded.validation import verify_suno_collection
from youtube_automation.utils.collection_paths import resolve_collection_dir
from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.skill_config import load_skill_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate suno-prompts.json and suno-lyrics.json artifacts")
    parser.add_argument("collection", nargs="?", help="collection directory (default: CWD)")
    args = parser.parse_args()

    try:
        collection_dir = resolve_collection_dir(args.collection)
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
