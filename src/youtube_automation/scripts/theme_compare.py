#!/usr/bin/env python3
"""yt-theme-compare: テーマ/コレクション別の launch curve 比較 CLI

Phase 1 の日次データと channel_config.theme_tags を組み合わせ、
各テーマの平均初速とロングテールを AI 消費向け JSON で出力する。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from youtube_automation.utils.config import channel_dir as _channel_dir
from youtube_automation.utils.config import load_config
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.launch_curve_data import (
    build_launch_curve_frame,
    load_latest_daily_snapshot,
)
from youtube_automation.utils.theme_performance import (
    analyze_theme_performance,
    classify_videos_by_theme,
)

logger = logging.getLogger(__name__)


def _load_video_meta(channel_dir: Path) -> dict:
    candidates = sorted((channel_dir / "data").glob("analytics_data_*.json"))
    if not candidates:
        raise ConfigError("analytics_data_*.json が見つかりません。先に `yt-analytics` を実行してください。")
    with open(candidates[-1], encoding="utf-8") as f:
        data = json.load(f)
    meta = {}
    for vid, v in (data.get("video_analytics") or {}).items():
        pub = v.get("published_at")
        if vid and pub:
            meta[vid] = {"title": v.get("title", ""), "published_at": pub}
    return meta


def _print_text_summary(analysis: dict) -> None:
    print("🎨 テーマ別パフォーマンス比較")
    print(f"   比較日齢: {analysis['peak_days']}")
    print(f"   最高初速: {analysis['best_theme_by_initial_velocity']}")
    print(f"   最高ロングテール: {analysis['best_theme_by_long_tail']}")
    print()
    for t in sorted(
        analysis["themes"],
        key=lambda x: x.get(f"day{analysis['peak_days'][0]}_mean") or 0,
        reverse=True,
    ):
        peaks_str = ", ".join(f"day{d}={t.get(f'day{d}_mean') or 'n/a'}" for d in analysis["peak_days"])
        print(f"   {t['theme']:<15} (n={t['video_count']}): {peaks_str}")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="テーマ別 launch curve 比較")
    parser.add_argument(
        "--peak-days",
        default="3,7,30",
        help="比較する日齢 (カンマ区切り, default: 3,7,30)",
    )
    parser.add_argument("--text", action="store_true", help="人間向けテキスト出力")

    args = parser.parse_args()
    peak_days = tuple(int(d) for d in args.peak_days.split(","))

    try:
        channel_dir = _channel_dir()
        config = load_config()

        daily = load_latest_daily_snapshot(channel_dir / "data")
        if daily is None:
            raise ConfigError("日次データが見つかりません。先に `yt-analytics` を実行してください。")
        meta = _load_video_meta(channel_dir)
        df = build_launch_curve_frame(daily_data=daily, video_meta=meta)
        if df.empty:
            raise ConfigError("launch curve 用データが空です")

        theme_keywords = config.content.tags.themes or {}
        if not theme_keywords:
            raise ConfigError("channel_config.tags.themes が未設定です。テーマ比較を行うには設定してください。")

        theme_video_map = classify_videos_by_theme(meta, theme_keywords)
        analysis = analyze_theme_performance(df, theme_video_map, peak_days=peak_days)

        if args.text:
            _print_text_summary(analysis)
        else:
            print(json.dumps(analysis, ensure_ascii=False, indent=2))
        return 0

    except ConfigError as e:
        logger.error(str(e))
        return 2
    except Exception as e:
        logger.exception(f"エラー: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
