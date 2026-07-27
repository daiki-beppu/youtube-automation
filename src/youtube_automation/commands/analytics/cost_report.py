"""yt-cost-report — 画像 / 動画 / 音楽 生成の累積コストサマリ + API quota 集計。

Usage:
    yt-cost-report                    # 全カテゴリのサマリ（quota 記録があれば quota 集計も表示）
    yt-cost-report --category image   # カテゴリを絞り込む
    yt-cost-report --month 2026-04    # 月で絞り込む
    yt-cost-report --detail           # 個別エントリを全件表示
    yt-cost-report --quota            # API quota 消費サマリのみ表示
    yt-cost-report --quota --detail   # quota 個別エントリを表示
"""

from __future__ import annotations

import argparse
import sys
from typing import get_args

from youtube_automation.infrastructure import cost_tracker
from youtube_automation.infrastructure.cost_tracker import Category


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


def _print_quota_detail(entries: list[dict]) -> None:
    if not entries:
        print("該当エントリなし")
        return
    print()
    print("=== Quota Entries ===")
    for e in entries:
        meta = e.get("metadata") or {}
        extra = " ".join(f"{k}={v}" for k, v in meta.items())
        print(f"  {e['timestamp']}  [{e['service']}]  {e['bucket']}  {e['units']} units  {extra}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="画像 / 動画 / 音楽 生成の累積コストサマリ + API quota 集計")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--category",
        choices=_categories(),
        help="指定カテゴリのみ表示（image / video / audio / analysis）",
    )
    scope.add_argument("--quota", action="store_true", help="API quota 消費のみ表示")
    parser.add_argument("--month", help="YYYY-MM で指定月のみに絞り込む（--detail と併用可）")
    parser.add_argument("--detail", action="store_true", help="個別エントリをすべて表示")
    args = parser.parse_args()

    if args.quota:
        if not args.detail:
            cost_tracker.print_quota_summary()
            return 0
        entries = cost_tracker.read_quota_log()
        if args.month:
            entries = [e for e in entries if e.get("timestamp", "").startswith(args.month)]
        _print_quota_detail(entries)
        return 0

    if not args.detail:
        cost_tracker.print_summary(args.category)
        # quota 記録があるときだけ併記する（quota 未導入の既存データでは従来表示のまま）
        if not args.category and cost_tracker.read_quota_log():
            cost_tracker.print_quota_summary()
        return 0

    entries = cost_tracker.read_log(args.category) if args.category else cost_tracker.read_all()
    if args.month:
        entries = [e for e in entries if e.get("timestamp", "").startswith(args.month)]
    _print_detail(entries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
