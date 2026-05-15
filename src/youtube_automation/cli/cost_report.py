"""yt-cost-report — 画像 / 動画 / 音楽 生成の累積コストサマリ。

Usage:
    yt-cost-report                    # 全カテゴリのサマリ（カテゴリ別 / 月別 / モデル別）
    yt-cost-report --category image   # カテゴリを絞り込む
    yt-cost-report --month 2026-04    # 月で絞り込む
    yt-cost-report --detail           # 個別エントリを全件表示
"""

from __future__ import annotations

import argparse
import sys
from typing import get_args

from youtube_automation.utils import cost_tracker
from youtube_automation.utils.cost_tracker import Category


def _categories() -> list[str]:
    return list(get_args(Category))


def _print_detail(entries: list[dict]) -> None:
    if not entries:
        print("該当エントリなし")
        return
    print()
    print("=== Entries ===")
    for e in entries:
        meta = e.get("metadata") or {}
        out = meta.get("output_file", "-")
        extra = " ".join(f"{k}={v}" for k, v in meta.items() if k != "output_file")
        cost = e.get("estimated_cost_usd")
        cost_label = f"${cost:.4f}" if isinstance(cost, (int, float)) else "-"
        print(
            f"  {e['timestamp']}  [{e['category']:>5s}]  {e['model']}  "
            f"{e['quantity']}{e['unit']}  {cost_label}  {out}  {extra}"
        )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="画像 / 動画 / 音楽 生成の累積コストサマリ")
    parser.add_argument(
        "--category",
        choices=_categories(),
        help="指定カテゴリのみ表示（image / video / audio）",
    )
    parser.add_argument("--month", help="YYYY-MM で指定月のみに絞り込む（--detail と併用可）")
    parser.add_argument("--detail", action="store_true", help="個別エントリをすべて表示")
    args = parser.parse_args()

    if not args.detail:
        cost_tracker.print_summary(args.category)
        return 0

    entries = cost_tracker.read_log(args.category) if args.category else cost_tracker.read_all()
    if args.month:
        entries = [e for e in entries if e.get("timestamp", "").startswith(args.month)]
    _print_detail(entries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
