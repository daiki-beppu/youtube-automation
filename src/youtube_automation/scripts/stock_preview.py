#!/usr/bin/env python3
"""``assets/stock/`` の画像を ``open`` で macOS プレビュー起動する CLI。

Usage:
    yt-stock-preview --theme tavern             # tavern テーマを全件 open
    yt-stock-preview --theme tavern --limit 5
    yt-stock-preview --source-role ideate_preview
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

from youtube_automation.utils.config import channel_dir
from youtube_automation.utils.stock import SOURCE_ROLES, list_stock


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="assets/stock/ の画像をプレビュー起動する")
    parser.add_argument("--theme", help="特定テーマ slug でフィルタ")
    parser.add_argument(
        "--source-role",
        choices=SOURCE_ROLES,
        help="source_role でフィルタ",
    )
    parser.add_argument("--limit", type=int, default=12, help="open する最大件数 (default: 12)")
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="open せずパスのみ標準出力 (macOS 以外 / テスト用)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    entries = list_stock(
        channel_dir(),
        theme=args.theme,
        source_role=args.source_role,
        limit=args.limit,
    )
    paths = [str(e.image_path) for e in entries]

    if not paths:
        print("(no stock entries match)", file=sys.stderr)
        return 0

    if args.print_only or shutil.which("open") is None:
        for p in paths:
            print(p)
        return 0

    subprocess.run(["open", *paths], check=False)
    print(f"opened {len(paths)} image(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
