#!/usr/bin/env python3
"""``assets/stock/`` の画像エントリを列挙する CLI。

Usage:
    yt-stock-list                                  # 全テーマ表形式
    yt-stock-list --theme tavern                   # 特定テーマ
    yt-stock-list --source-role thumbnail_candidate
    yt-stock-list --format json --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys

from youtube_automation.configuration import channel_dir
from youtube_automation.utils.stock import SOURCE_ROLES, list_stock


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="assets/stock/ の画像エントリを列挙する")
    parser.add_argument("--theme", help="特定テーマ slug でフィルタ")
    parser.add_argument(
        "--source-role",
        choices=SOURCE_ROLES,
        help="source_role でフィルタ",
    )
    parser.add_argument("--limit", type=int, help="返却件数の上限 (新しい順)")
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="出力形式 (default: table)",
    )
    return parser


def _format_table(entries: list[dict]) -> str:
    if not entries:
        return "(empty)"
    headers = ["theme", "role", "generated_at", "path"]
    rows = [headers]
    for e in entries:
        rows.append(
            [
                e.get("theme", ""),
                e.get("source_role") or "",
                e.get("generated_at") or "",
                e.get("path", ""),
            ]
        )
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(headers))]
    lines = []
    for index, row in enumerate(rows):
        line = "  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))
        lines.append(line)
        if index == 0:
            lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    entries = list_stock(
        channel_dir(),
        theme=args.theme,
        source_role=args.source_role,
        limit=args.limit,
    )

    payload = [
        {
            "theme": e.theme,
            "path": str(e.image_path),
            "source_role": e.source_role,
            "generated_at": e.generated_at,
            "source_collection": e.meta.get("source_collection"),
        }
        for e in entries
    ]

    if args.format == "json":
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
    else:
        print(_format_table(payload))
        print()
        print(f"total: {len(payload)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
