#!/usr/bin/env python3
"""yt-launch-curve: 新作動画の初速をベンチマーク比較する CLI"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from youtube_automation.utils.channel_config import ChannelConfig
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.launch_curve_analyzer import (
    compute_benchmark,
    judge_video_vs_benchmark,
)
from youtube_automation.utils.launch_curve_data import (
    build_launch_curve_frame,
    load_latest_daily_snapshot,
)
from youtube_automation.utils.launch_curve_plotter import plot_launch_curve

logger = logging.getLogger(__name__)


def _load_video_meta(channel_dir: Path) -> dict:
    """data/ 配下の最新 analytics_data_*.json から video meta を抽出する"""
    candidates = sorted((channel_dir / "data").glob("analytics_data_*.json"))
    if not candidates:
        raise ConfigError(
            "analytics_data_*.json が見つかりません。先に `yt-analytics` を実行してください。"
        )
    with open(candidates[-1], encoding="utf-8") as f:
        data = json.load(f)

    meta = {}
    video_analytics = data.get("video_analytics", {}) or {}
    # video_analytics は {video_id: {...}} の dict 形式
    for vid, v in video_analytics.items():
        pub = v.get("published_at")
        if vid and pub:
            meta[vid] = {"title": v.get("title", ""), "published_at": pub}
    return meta


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="動画の launch curve を過去ベンチマークと比較")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--video", help="対象動画 ID")
    group.add_argument("--latest", action="store_true", help="最新公開動画を自動選択")
    group.add_argument("--all", action="store_true", help="全動画を重ね描き（ベンチマーク把握用）")
    parser.add_argument("--window", type=int, default=30, help="表示日数 (default: 30)")

    args = parser.parse_args()

    try:
        channel_dir = ChannelConfig.channel_dir()
        daily = load_latest_daily_snapshot(channel_dir / "data")
        if daily is None:
            raise ConfigError(
                "日次データが見つかりません。先に `yt-analytics` を実行してください。"
            )
        meta = _load_video_meta(channel_dir)
        df = build_launch_curve_frame(daily_data=daily, video_meta=meta)
        if df.empty:
            raise ConfigError("launch curve 用データが空です")

        if args.all:
            target_id = None
        elif args.latest:
            target_id = df.sort_values("published_at", ascending=False)["video_id"].iloc[0]
        else:
            target_id = args.video

        out_dir = channel_dir / "data" / "analytics" / "launch_curves"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d")
        suffix = target_id if target_id else "all"
        out_path = out_dir / f"{stamp}_{suffix}.png"

        plot_launch_curve(df=df, target_video_id=target_id, output_path=out_path, window=args.window)

        if target_id:
            bench = compute_benchmark(df, metric="cumulative_views", exclude_video_id=target_id)
            target = df[df["video_id"] == target_id]
            latest_day = int(target["days_since_publish"].max())
            j = judge_video_vs_benchmark(df, bench, target_id, latest_day)
            print(f"🎯 {target_id} ({meta.get(target_id, {}).get('title', '')})")
            print(f"   {latest_day}日時点 累積 views: {int(j['value']):,}")
            if j.get("benchmark_median") is not None:
                print(f"   ベンチマーク中央値: {int(j['benchmark_median']):,} "
                      f"(n={j['sample_size']})")
                print(f"   判定: {j['quartile_label']} (中央値の {j['ratio_vs_median']:.2f}x)")
            else:
                print(f"   判定: {j['quartile_label']}")
        print(f"📈 プロット: {out_path}")
        return 0

    except ConfigError as e:
        logger.error(str(e))
        return 2
    except Exception as e:
        logger.exception(f"エラー: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
