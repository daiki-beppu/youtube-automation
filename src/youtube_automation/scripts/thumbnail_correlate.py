#!/usr/bin/env python3
"""yt-thumbnail-correlate: サムネ特徴量 × CTR の相関を出力する CLI

各動画のサムネを YouTube から取得 (ローカルキャッシュ) し、
brightness/contrast/saturation/dominant_hue/colorfulness を抽出。
impression_ctr との Pearson 相関を AI 消費向け JSON で出力する。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.request
from pathlib import Path

from PIL import Image

from youtube_automation.utils.config import channel_dir as _channel_dir
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.thumbnail_correlation import compute_correlations
from youtube_automation.utils.thumbnail_features import extract_features

logger = logging.getLogger(__name__)

THUMB_URL_TEMPLATES = [
    "https://img.youtube.com/vi/{vid}/maxresdefault.jpg",
    "https://img.youtube.com/vi/{vid}/hqdefault.jpg",
]


def _load_analytics(channel_dir: Path) -> dict:
    candidates = sorted((channel_dir / "data").glob("analytics_data_*.json"))
    if not candidates:
        raise ConfigError("analytics_data_*.json が見つかりません。先に `yt-analytics` を実行してください。")
    with open(candidates[-1], encoding="utf-8") as f:
        return json.load(f)


def _fetch_thumbnail(video_id: str, cache_dir: Path) -> Path:
    """YouTube からサムネをダウンロードしてローカルキャッシュに保存。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{video_id}.jpg"
    if cache_file.exists() and cache_file.stat().st_size > 1000:
        return cache_file

    last_err = None
    for tmpl in THUMB_URL_TEMPLATES:
        url = tmpl.format(vid=video_id)
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = resp.read()
            if len(data) < 1000:
                continue
            cache_file.write_bytes(data)
            return cache_file
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"サムネ取得失敗 ({video_id}): {last_err}")


def _resolve_metric(data: dict, ctr_map: dict, vid: str, metric: str) -> float | None:
    """動画の目的変数 (ctr/views/engagement) を解決する。"""
    if metric == "ctr":
        ctr = ctr_map.get(vid) or data.get("impression_ctr") or data.get("click_through_rate")
        return float(ctr) if ctr else None
    if metric == "views":
        v = data.get("views")
        return float(v) if v else None
    if metric == "engagement":
        v = data.get("views") or 0
        if v <= 0:
            return None
        engagement = (data.get("likes") or 0) + (data.get("comments") or 0) + (data.get("shares") or 0)
        return engagement / v * 100
    return None


def _collect_video_features(
    analytics_data: dict,
    cache_dir: Path,
    metric: str,
) -> list[dict]:
    va = analytics_data.get("video_analytics") or {}
    vp = (analytics_data.get("ctr_analysis") or {}).get("video_performance") or []
    ctr_map = {v["video_id"]: v.get("impression_ctr") for v in vp if v.get("impression_ctr")}

    if metric == "ctr" and not ctr_map and not any(data.get("click_through_rate") for data in va.values()):
        logger.warning(
            "動画別 CTR データが取得できていません（API 仕様上 impressions/CTR は動画別に取れません）。"
            "--metric views または --metric engagement の利用を検討してください。"
        )

    videos = []
    for vid, data in va.items():
        value = _resolve_metric(data, ctr_map, vid, metric)
        if value is None:
            logger.debug(f"skip {vid}: {metric} なし")
            continue
        try:
            thumb_path = _fetch_thumbnail(vid, cache_dir)
            img = Image.open(thumb_path)
            features = extract_features(img)
        except Exception as e:
            logger.warning(f"{vid} のサムネ処理失敗: {e}")
            continue

        videos.append(
            {
                "video_id": vid,
                "title": data.get("title", ""),
                "ctr": float(value),  # key は互換性のため "ctr" のまま
                "features": features,
            }
        )
    return videos


def _print_text_summary(analysis: dict) -> None:
    metric = analysis.get("metric", "ctr")
    print(f"🖼️  サムネ × {metric} 相関分析 (n={analysis['video_count']})")
    print()
    # 絶対値で降順
    corrs = analysis["correlations"]
    sorted_corrs = sorted(
        corrs.items(),
        key=lambda kv: abs(kv[1]["pearson"]) if kv[1]["pearson"] is not None else -1,
        reverse=True,
    )
    for key, c in sorted_corrs:
        r = c["pearson"]
        note = c.get("interpretation") or c.get("note", "")
        if r is None:
            print(f"   {key:<30} r=   n/a  ({note})")
        else:
            print(f"   {key:<30} r={r:+.3f}  n={c['n']}  {note}")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="サムネ特徴量 × CTR 相関分析")
    parser.add_argument("--text", action="store_true", help="人間向けテキスト出力")
    parser.add_argument(
        "--metric",
        choices=["ctr", "views", "engagement"],
        default="ctr",
        help="相関対象 (ctr: 優先だがチャンネルが閾値未達だと空、"
        "views: 視聴回数, engagement: (likes+comments+shares)/views)",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=5,
        help="相関計算に必要な最小サンプル数 (default: 5)",
    )

    args = parser.parse_args()

    try:
        channel_dir = _channel_dir()
        analytics = _load_analytics(channel_dir)
        cache_dir = channel_dir / "data" / "analytics" / "thumbnails"

        videos = _collect_video_features(analytics, cache_dir, args.metric)
        corrs = compute_correlations(videos, min_samples=args.min_samples)

        result = {
            "metric": args.metric,
            "video_count": len(videos),
            "correlations": corrs,
            "videos": videos,
        }

        if args.text:
            _print_text_summary(result)
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    except ConfigError as e:
        logger.error(str(e))
        return 2
    except Exception as e:
        logger.exception(f"エラー: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
