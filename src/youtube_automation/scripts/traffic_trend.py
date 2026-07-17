#!/usr/bin/env python3
"""yt-traffic-trend: 流入源シェア推移とデバイス別集計を出力する CLI

既存の analytics_data_*.json（standard 以上の depth で収集したもの）から
traffic_sources / audience.by_device を読み込み、スナップショット横断の
シェア推移・最新デバイス集計・YT_SEARCH 検索語トップ N を JSON で出力する。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from youtube_automation.utils.config import channel_dir as _channel_dir
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.traffic_trend import analyze_traffic_trend

logger = logging.getLogger(__name__)


def _load_snapshots(channel_dir: Path) -> list[dict]:
    """data/ 配下の analytics_data_*.json を辞書順（=時系列昇順）で読み込む"""
    candidates = sorted((channel_dir / "data").glob("analytics_data_*.json"))
    if not candidates:
        raise ConfigError("analytics_data_*.json が見つかりません。先に `yt-analytics` を実行してください。")
    snapshots = []
    for path in candidates:
        with open(path, encoding="utf-8") as f:
            snapshots.append(json.load(f))
    return snapshots


def _print_text_summary(analysis: dict) -> None:
    s = analysis["summary"]
    print("🚦 流入源・デバイス分析")
    print(f"   分析スナップショット数: {analysis['snapshots_analyzed']}")
    print(f"   最大流入源: {s['top_source']} ({s['top_source_share_percent']}%)")
    print(f"   最大デバイス: {s['top_device']} ({s['top_device_share_percent']}%)")

    latest = analysis["latest"]
    print("\n📊 最新スナップショットの流入源シェア:")
    for name, data in sorted(latest["sources"].items(), key=lambda kv: kv[1].get("views", 0), reverse=True):
        delta = s["share_delta"].get(name)
        delta_str = f" ({delta:+.1f}pt)" if delta is not None else ""
        print(f"   {name}: {data.get('view_share_percent', 0)}%{delta_str}  views={data.get('views', 0):,}")

    print("\n📱 デバイス別:")
    for name, data in sorted(latest["devices"].items(), key=lambda kv: kv[1].get("views", 0), reverse=True):
        print(f"   {name}: {data.get('view_share_percent', 0)}%  views={data.get('views', 0):,}")

    if latest["search_terms"]:
        print("\n🔍 YT_SEARCH 検索語トップ:")
        for term in latest["search_terms"]:
            print(f"   {term.get('detail')}: {term.get('views', 0):,} views")
    else:
        print("\n🔍 YT_SEARCH 検索語: データなし（`yt-analytics` の再収集で取得）")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="流入源シェア推移とデバイス別集計")
    parser.add_argument(
        "--top-search",
        type=int,
        default=10,
        help="YT_SEARCH 検索語トップ N の件数 (default: 10)",
    )
    parser.add_argument("--text", action="store_true", help="人間向けテキスト出力")

    args = parser.parse_args()

    try:
        channel_dir = _channel_dir()
        snapshots = _load_snapshots(channel_dir)
        analysis = analyze_traffic_trend(snapshots, top_search=args.top_search)

        if analysis["snapshots_analyzed"] == 0:
            raise ConfigError(
                "traffic_sources を含むスナップショットがありません。"
                "`yt-analytics --depth standard` 以上で再収集してください。"
            )

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
