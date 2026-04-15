#!/usr/bin/env python3
"""yt-launch-curve: 新作動画の初速をベンチマーク比較する CLI

デフォルトは AI 消費向けの構造化 JSON を stdout に出力する。
--text で人間向けサマリー、--png で可視化 PNG を追加出力。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

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
    for vid, v in video_analytics.items():
        pub = v.get("published_at")
        if vid and pub:
            meta[vid] = {"title": v.get("title", ""), "published_at": pub}
    return meta


def _build_analysis(
    df: pd.DataFrame,
    meta: Dict,
    target_id: Optional[str],
    window: int,
) -> Dict:
    """AI 消費向けの構造化分析結果を組み立てる"""
    df_win = df[df["days_since_publish"] <= window]
    bench = compute_benchmark(
        df_win, metric="cumulative_views", exclude_video_id=target_id
    )

    # 各動画の「最新日齢時点」のスナップショット
    latest_per_video = (
        df_win.sort_values("days_since_publish")
        .groupby("video_id")
        .tail(1)
        .reset_index(drop=True)
    )
    all_videos: List[Dict] = []
    for _, row in latest_per_video.iterrows():
        vid = row["video_id"]
        day = int(row["days_since_publish"])
        j = judge_video_vs_benchmark(df_win, bench, vid, day)
        all_videos.append({
            "video_id": vid,
            "title": meta.get(vid, {}).get("title", ""),
            "published_at": meta.get(vid, {}).get("published_at"),
            "latest_day": day,
            "cumulative_views": int(row["cumulative_views"]),
            "latest_ctr": float(row["ctr"]) if pd.notna(row["ctr"]) else None,
            "ratio_vs_median": j.get("ratio_vs_median"),
            "quartile_label": j.get("quartile_label"),
            "sample_size": j.get("sample_size"),
        })
    all_videos.sort(
        key=lambda v: v["ratio_vs_median"] if v["ratio_vs_median"] is not None else -1,
        reverse=True,
    )

    target_block: Optional[Dict] = None
    if target_id:
        target_rows = df_win[df_win["video_id"] == target_id]
        if not target_rows.empty:
            latest_day = int(target_rows["days_since_publish"].max())
            j = judge_video_vs_benchmark(df_win, bench, target_id, latest_day)
            # 日別トレース
            trace = [
                {
                    "days_since_publish": int(r["days_since_publish"]),
                    "date": str(r["date"].date()),
                    "daily_views": int(r["daily_views"]),
                    "cumulative_views": int(r["cumulative_views"]),
                    "daily_impressions": int(r["daily_impressions"]),
                    "ctr": float(r["ctr"]) if pd.notna(r["ctr"]) else None,
                }
                for _, r in target_rows.sort_values("days_since_publish").iterrows()
            ]
            target_block = {
                "video_id": target_id,
                "title": meta.get(target_id, {}).get("title", ""),
                "published_at": meta.get(target_id, {}).get("published_at"),
                "at_day": latest_day,
                "value": j.get("value"),
                "ratio_vs_median": j.get("ratio_vs_median"),
                "quartile_label": j.get("quartile_label"),
                "benchmark_median": j.get("benchmark_median"),
                "benchmark_p25": j.get("benchmark_p25"),
                "benchmark_p75": j.get("benchmark_p75"),
                "sample_size": j.get("sample_size"),
                "trace": trace,
            }

    benchmark_by_day = [
        {
            "day": int(r["days_since_publish"]),
            "p25": float(r["p25"]) if pd.notna(r["p25"]) else None,
            "p50": float(r["p50"]) if pd.notna(r["p50"]) else None,
            "p75": float(r["p75"]) if pd.notna(r["p75"]) else None,
            "sample_size": int(r["sample_size"]),
        }
        for _, r in bench.iterrows()
    ]

    return {
        "generated_at": datetime.now().isoformat(),
        "window_days": window,
        "data_date_range": {
            "min_date": str(df["date"].min().date()),
            "max_date": str(df["date"].max().date()),
        },
        "metric": "cumulative_views",
        "target": target_block,
        "benchmark_by_day": benchmark_by_day,
        "all_videos": all_videos,
    }


def _print_text_summary(analysis: Dict) -> None:
    t = analysis.get("target")
    if t:
        print(f"🎯 {t['video_id']} ({t['title']})")
        print(f"   {t['at_day']}日時点 累積 views: {t['value']:,.0f}")
        if t.get("benchmark_median") is not None:
            print(
                f"   ベンチマーク中央値: {t['benchmark_median']:,.0f} "
                f"(n={t['sample_size']})"
            )
            print(
                f"   判定: {t['quartile_label']} "
                f"(中央値の {t['ratio_vs_median']:.2f}x)"
            )
        else:
            print(f"   判定: {t['quartile_label']}")
    print("\n📊 全動画ランキング (最新日齢時点, 中央値比):")
    for v in analysis["all_videos"]:
        ratio = f"{v['ratio_vs_median']:.2f}x" if v["ratio_vs_median"] else "n/a"
        print(
            f"   {v['video_id']} day{v['latest_day']:>2}: "
            f"cum_views={v['cumulative_views']:>6,} "
            f"ratio={ratio:>7}  {v['quartile_label']}"
        )


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="動画の launch curve を過去ベンチマークと比較"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--video", help="対象動画 ID")
    group.add_argument("--latest", action="store_true", help="最新公開動画を自動選択")
    group.add_argument("--all", action="store_true", help="全動画ランキングのみ（target なし）")
    parser.add_argument("--window", type=int, default=30, help="表示日数 (default: 30)")
    parser.add_argument(
        "--text", action="store_true", help="JSON ではなく人間向けテキストで出力",
    )
    parser.add_argument(
        "--png", action="store_true", help="可視化 PNG も出力（デフォルトは出力しない）",
    )

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

        analysis = _build_analysis(df, meta, target_id, args.window)

        if args.png:
            from youtube_automation.utils.launch_curve_plotter import plot_launch_curve
            out_dir = channel_dir / "data" / "analytics" / "launch_curves"
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d")
            suffix = target_id if target_id else "all"
            out_path = out_dir / f"{stamp}_{suffix}.png"
            plot_launch_curve(
                df=df, target_video_id=target_id, output_path=out_path, window=args.window,
            )
            analysis["png_path"] = str(out_path)

        if args.text:
            _print_text_summary(analysis)
            if "png_path" in analysis:
                print(f"\n📈 プロット: {analysis['png_path']}")
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
