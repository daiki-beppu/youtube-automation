#!/usr/bin/env python3
"""収集済み収益データから広告カバレッジ低下の疑いを抽出する CLI。"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from youtube_automation.configuration import channel_dir as _channel_dir
from youtube_automation.core.errors import ConfigError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoAdCoverage:
    video_id: str
    monetized_playbacks: int
    ads_per_playback: float


def _parse_non_negative_float(value: object, *, field: str, video_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"revenue_analytics.by_video.{video_id}.{field} は数値で指定してください")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ConfigError(f"revenue_analytics.by_video.{video_id}.{field} は有限の非負数で指定してください")
    return parsed


def _parse_video_rows(by_video: object) -> list[VideoAdCoverage]:
    if not isinstance(by_video, Mapping):
        raise ConfigError("revenue_analytics.by_video は JSON object である必要があります")

    videos: list[VideoAdCoverage] = []
    for video_id, raw_metrics in by_video.items():
        if not isinstance(video_id, str) or not video_id:
            raise ConfigError("revenue_analytics.by_video の video ID は空でない文字列である必要があります")
        if not isinstance(raw_metrics, Mapping):
            raise ConfigError(f"revenue_analytics.by_video.{video_id} は JSON object である必要があります")

        playbacks = raw_metrics.get("monetized_playbacks")
        if isinstance(playbacks, bool) or not isinstance(playbacks, int) or playbacks < 0:
            raise ConfigError(
                f"revenue_analytics.by_video.{video_id}.monetized_playbacks は非負の整数で指定してください"
            )
        ads_per_playback = _parse_non_negative_float(
            raw_metrics.get("ads_per_playback"),
            field="ads_per_playback",
            video_id=video_id,
        )
        videos.append(VideoAdCoverage(video_id, playbacks, ads_per_playback))
    return videos


def analyze_ad_coverage(
    revenue_analytics: Mapping[str, object], *, threshold: float, min_playbacks: int
) -> dict[str, object]:
    """中央値比が閾値未満の動画を抽出する。"""
    if not 0 < threshold <= 1:
        raise ConfigError("threshold は 0 より大きく 1 以下で指定してください")
    if min_playbacks < 1:
        raise ConfigError("min_playbacks は 1 以上で指定してください")

    status = revenue_analytics.get("status")
    if status == "unavailable":
        reason = revenue_analytics.get("reason")
        if not isinstance(reason, str) or not reason:
            raise ConfigError("unavailable な revenue_analytics.reason は空でない文字列である必要があります")
        return {
            "status": "unavailable",
            "reason": reason,
            "warning_count": 0,
            "warnings": [],
        }
    if status != "available":
        raise ConfigError("revenue_analytics.status は available または unavailable である必要があります")

    videos = _parse_video_rows(revenue_analytics.get("by_video"))
    eligible = [video for video in videos if video.monetized_playbacks >= min_playbacks]
    median_value = float(median(video.ads_per_playback for video in eligible)) if eligible else None

    warnings: list[dict[str, object]] = []
    if median_value is not None and median_value > 0:
        for video in eligible:
            median_ratio = video.ads_per_playback / median_value
            if median_ratio < threshold:
                warnings.append(
                    {
                        "video_id": video.video_id,
                        "ads_per_playback": video.ads_per_playback,
                        "median_ratio": median_ratio,
                    }
                )
        warnings.sort(key=lambda warning: (float(warning["median_ratio"]), str(warning["video_id"])))

    return {
        "status": "available",
        "threshold": threshold,
        "min_playbacks": min_playbacks,
        "eligible_video_count": len(eligible),
        "median_ads_per_playback": median_value,
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def load_latest_revenue(channel_root: Path) -> Mapping[str, object]:
    """最新 analytics snapshot の revenue_analytics を検証して返す。"""
    candidates = sorted((channel_root / "data").glob("analytics_data_*.json"))
    if not candidates:
        raise ConfigError("analytics_data_*.json が見つかりません。先に `yt-analytics` を実行してください。")
    path = candidates[-1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise ConfigError(f"{path.name} を読み込めません: {error}") from error
    if not isinstance(payload, Mapping):
        raise ConfigError(f"{path.name} は JSON object である必要があります")
    revenue = payload.get("revenue_analytics")
    if not isinstance(revenue, Mapping):
        raise ConfigError(f"{path.name}.revenue_analytics は JSON object である必要があります")
    return revenue


def _threshold(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("0 より大きく 1 以下の数値を指定してください") from error
    if not math.isfinite(parsed) or not 0 < parsed <= 1:
        raise argparse.ArgumentTypeError("0 より大きく 1 以下の数値を指定してください")
    return parsed


def _min_playbacks(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("1 以上の整数を指定してください") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("1 以上の整数を指定してください")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="動画別 ads-per-playback の中央値から広告カバレッジ低下を検出")
    parser.add_argument(
        "--threshold",
        type=_threshold,
        default=0.5,
        help="警告対象とする中央値比の上限（未満、default: 0.5）",
    )
    parser.add_argument(
        "--min-playbacks",
        type=_min_playbacks,
        default=100,
        help="中央値計算と警告に含める最小 monetized playback 数（default: 100）",
    )
    parser.add_argument("--text", action="store_true", help="人間向けテキスト出力")
    return parser


def _print_text(analysis: Mapping[str, object]) -> None:
    if analysis["status"] == "unavailable":
        print(f"収益データを取得できません: {analysis['reason']}")
        return

    print("広告カバレッジ診断")
    print(f"対象動画: {analysis['eligible_video_count']} 件")
    median_value = analysis["median_ads_per_playback"]
    if isinstance(median_value, float):
        print(f"ads-per-playback 中央値: {median_value:.4f}")
    else:
        print("ads-per-playback 中央値: 算出対象なし")
    print(f"警告: {analysis['warning_count']} 件")
    for warning in analysis["warnings"]:
        if not isinstance(warning, Mapping):
            raise ConfigError("warnings の内部契約が不正です")
        print(
            "ミッドロール広告が欠けた疑い: "
            f"{warning['video_id']} "
            f"ads-per-playback={float(warning['ads_per_playback']):.4f} "
            f"中央値比={float(warning['median_ratio']):.1%}"
        )


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    args = _build_parser().parse_args()
    try:
        revenue = load_latest_revenue(_channel_dir())
        analysis = analyze_ad_coverage(revenue, threshold=args.threshold, min_playbacks=args.min_playbacks)
        if args.text:
            _print_text(analysis)
        else:
            print(json.dumps(analysis, ensure_ascii=False, indent=2))
        return 0
    except ConfigError as error:
        logger.error(str(error))
        return 2


if __name__ == "__main__":
    sys.exit(main())
