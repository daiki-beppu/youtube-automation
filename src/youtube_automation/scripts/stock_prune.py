#!/usr/bin/env python3
"""``assets/stock/`` の古い画像 / テーマあたり上限超過分を削除する CLI。

skill-config の ``image_generation.stock.retention_days`` / ``max_per_theme``
が default 値として使われる。CLI で明示指定したらそれを優先する。

Usage:
    yt-stock-prune --dry-run                     # 削除候補のみ表示
    yt-stock-prune                                # config 値で削除
    yt-stock-prune --retention-days 30 --max-per-theme 20
"""

from __future__ import annotations

import argparse
import sys

from youtube_automation.utils.config import channel_dir
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.stock import load_stock_config, prune_stock


def _resolve_defaults(args: argparse.Namespace) -> tuple[int | None, int | None]:
    """skill-config の値をデフォルトとして取り込む。

    CLI で明示指定がある場合はそれを優先、未指定なら config 値。
    config も無ければ ``None`` (該当条件はスキップ)。
    """

    stock = load_stock_config(load_skill_config("thumbnail"))

    retention = args.retention_days
    if retention is None:
        retention = stock.get("retention_days")

    max_per = args.max_per_theme
    if max_per is None:
        max_per = stock.get("max_per_theme")

    return (
        int(retention) if retention is not None else None,
        int(max_per) if max_per is not None else None,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="assets/stock/ の古い画像を削除する")
    parser.add_argument("--theme", help="特定テーマ slug のみ対象 (未指定で全テーマ)")
    parser.add_argument("--retention-days", type=int, help="保持日数 (mtime 基準)")
    parser.add_argument("--max-per-theme", type=int, help="テーマあたりの最大保持件数")
    parser.add_argument("--dry-run", action="store_true", help="削除せず候補のみ表示")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    retention, max_per = _resolve_defaults(args)
    if retention is None and max_per is None:
        print(
            "[ERROR] --retention-days か --max-per-theme のいずれかを指定するか、"
            "config/skills/thumbnail.yaml の image_generation.stock に既定値を設定してください",
            file=sys.stderr,
        )
        return 2

    targets = prune_stock(
        channel_dir(),
        theme=args.theme,
        retention_days=retention,
        max_per_theme=max_per,
        dry_run=args.dry_run,
    )

    if not targets:
        print("(no entries to prune)")
        return 0

    label = "[DRY]" if args.dry_run else "[PRUNE]"
    for path in targets:
        print(f"  {label}  {path}")
    print()
    print(f"total: {len(targets)} (retention_days={retention} max_per_theme={max_per})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
