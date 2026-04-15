#!/usr/bin/env python3
"""yt-channel-trend: チャンネル全体の日次トレンドと異常検知を出力する CLI

既存の analytics_data_*.json から channel_analytics.daily_metrics を読み込み、
移動平均・WoW 成長率・スパイク/ディップ検知を計算して JSON で出力する。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from youtube_automation.utils.channel_config import ChannelConfig
from youtube_automation.utils.channel_trend import analyze_channel_trend
from youtube_automation.utils.exceptions import ConfigError

logger = logging.getLogger(__name__)


def _load_daily_metrics(channel_dir: Path):
    """最新 analytics_data_*.json から daily_metrics を取り出す"""
    candidates = sorted((channel_dir / "data").glob("analytics_data_*.json"))
    if not candidates:
        raise ConfigError(
            "analytics_data_*.json が見つかりません。先に `yt-analytics` を実行してください。"
        )
    with open(candidates[-1], encoding="utf-8") as f:
        data = json.load(f)
    ca = data.get("channel_analytics") or {}
    return ca.get("daily_metrics") or []


def _print_text_summary(analysis: dict) -> None:
    s = analysis["summary"]
    period = s.get("period") or {}
    print("📊 チャンネルトレンド分析")
    print(f"   期間: {period.get('start_date')} 〜 {period.get('end_date')} "
          f"({period.get('days')}日)")
    print(f"   合計 views: {s['total_views']:,}")
    print(f"   登録者増加: +{s['total_subs_gained']} / -{s['total_subs_lost']}")
    print(f"   平均日次 views: {s['avg_daily_views']:.1f}")
    arrow = {"up": "📈", "down": "📉", "flat": "➡️"}.get(s["trend_direction"], "")
    print(f"   トレンド: {arrow} {s['trend_direction']}")
    if s.get("wow_growth_rate") is not None:
        print(f"   直近週の前週比: {s['wow_growth_rate']:+.1f}%")

    anomalies = analysis["anomalies"]
    if anomalies:
        print("\n🚨 異常検知 (z_score ≥ 2):")
        for a in anomalies:
            icon = "🔺" if a["type"] == "spike" else "🔻"
            print(f"   {icon} {a['date']} views={a['views']:,} "
                  f"(z={a['z_score']}, 7d_ma={a['baseline_7d_ma']})")
    else:
        print("\n🚨 異常検知: なし")

    wow = analysis["week_over_week"]
    if wow:
        print("\n📅 週次推移:")
        for w in wow[-6:]:
            delta = f"{w['delta_pct']:+.1f}%" if w['delta_pct'] is not None else "  —"
            print(f"   {w['week_starting']}: {w['views']:>6,} views  ({delta})")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="チャンネル全体の日次トレンドと異常検知"
    )
    parser.add_argument(
        "--z-threshold", type=float, default=2.0,
        help="異常検知の z-score 閾値 (default: 2.0)",
    )
    parser.add_argument("--text", action="store_true", help="人間向けテキスト出力")

    args = parser.parse_args()

    try:
        channel_dir = ChannelConfig.channel_dir()
        daily_metrics = _load_daily_metrics(channel_dir)
        analysis = analyze_channel_trend(daily_metrics, z_threshold=args.z_threshold)

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
