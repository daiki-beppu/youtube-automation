#!/usr/bin/env python3
"""承認済みサムネイルをチャンネルの thumbnail gallery へ保存する。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from youtube_automation.configuration import channel_dir
from youtube_automation.domains.thumbnail.archive import archive_approved_thumbnail
from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.skill_config import load_skill_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="承認済み thumbnail.jpg/png をギャラリーへ保存する")
    parser.add_argument("collection", type=Path, help="対象コレクションディレクトリ")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    collection = args.collection.resolve()
    paths = CollectionPaths(collection)
    if not collection.is_dir() or not paths.assets_dir.is_dir():
        print(f"error: コレクションディレクトリではありません (10-assets/ が必要): {collection}", file=sys.stderr)
        return 2

    try:
        config = load_skill_config("thumbnail")
        archived = archive_approved_thumbnail(
            collection,
            archive_config=config,
            channel_root=channel_dir(),
        )
    except (ConfigError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if archived is None:
        print("[archive] disabled: thumbnail archive was not created")
    else:
        print(f"[archive] {archived}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
