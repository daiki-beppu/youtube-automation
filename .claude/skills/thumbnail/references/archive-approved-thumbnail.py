#!/usr/bin/env python3
"""承認済みサムネイルをチャンネルの thumbnail gallery へ保存する。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.thumbnail_archive import archive_approved_thumbnail


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
        archived = archive_approved_thumbnail(collection)
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
