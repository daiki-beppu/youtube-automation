"""Launch curve 分析用の DataFrame 構築ユーティリティ"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from youtube_automation.infrastructure.analytics.ctr_resolver import index_reporting_per_video
from youtube_automation.infrastructure.analytics.snapshots import load_latest_analytics_snapshot


def build_launch_curve_frame(
    daily_data: Dict,
    video_meta: Dict[str, Dict],
    reporting_snapshot: Optional[Dict] = None,
) -> pd.DataFrame:
    """
    永続化 JSON と動画メタから launch curve 用 DataFrame を構築する。

    Args:
        daily_data: {"rows": [{video_id, date, views, impressions?, impression_ctr?}, ...]}
            `video_id` / `date` / `views` are required. Missing `impressions`
            is normalized to `daily_impressions=0`; missing `impression_ctr`
            keeps `ctr` unavailable.
        video_meta: {video_id: {"title": ..., "published_at": "ISO-8601"}}
        reporting_snapshot: Reporting API v1 由来の impressions_summary (#84)。
            指定された場合、per_video の CTR / impressions を `reporting_ctr_snapshot`
            / `reporting_impressions_snapshot` 列として全行に broadcast する。

    Returns:
        DataFrame with columns:
          video_id, date (datetime), published_at (datetime),
          days_since_publish (int), daily_views, cumulative_views,
          daily_impressions, ctr,
          reporting_ctr_snapshot, reporting_impressions_snapshot
    """
    base_columns = [
        "video_id",
        "date",
        "published_at",
        "days_since_publish",
        "daily_views",
        "cumulative_views",
        "daily_impressions",
        "ctr",
        "reporting_ctr_snapshot",
        "reporting_impressions_snapshot",
    ]

    rows = daily_data.get("rows", [])
    if not rows:
        return pd.DataFrame(columns=base_columns)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    # published_at を日付に正規化（時刻成分で days_since_publish が1日ズレるのを防ぐ）
    meta_df = pd.DataFrame(
        [
            {
                "video_id": vid,
                "published_at": pd.to_datetime(m["published_at"]).tz_localize(None).normalize(),
            }
            for vid, m in video_meta.items()
        ]
    )
    df = df.merge(meta_df, on="video_id", how="inner")

    df["days_since_publish"] = (df["date"] - df["published_at"]).dt.days
    df = df[df["days_since_publish"] >= 0]

    df = df.rename(
        columns={
            "views": "daily_views",
            "impressions": "daily_impressions",
            "impression_ctr": "ctr",
        }
    )
    if "daily_impressions" not in df.columns:
        df["daily_impressions"] = 0
    if "ctr" not in df.columns:
        df["ctr"] = pd.NA
    df["daily_impressions"] = df["daily_impressions"].fillna(0)
    df["ctr"] = df["ctr"].astype("Float64")

    df = df.sort_values(["video_id", "days_since_publish"])
    df["cumulative_views"] = df.groupby("video_id")["daily_views"].cumsum()

    ra_index = index_reporting_per_video(reporting_snapshot)
    mapped = df["video_id"].map(lambda vid: ra_index.get(vid) or {})
    df["reporting_ctr_snapshot"] = mapped.map(lambda r: r.get("ctr_percentage"))
    df["reporting_impressions_snapshot"] = mapped.map(lambda r: r.get("impressions"))

    return df[base_columns].reset_index(drop=True)


def load_latest_daily_snapshot(channel_data_dir: Path) -> Optional[Dict]:
    """data/analytics/daily_per_video/ から最新の JSON を読み込む"""
    return _load_latest_snapshot(channel_data_dir / "analytics" / "daily_per_video")


def load_latest_reporting_snapshot(channel_data_dir: Path) -> Optional[Dict]:
    """data/analytics/reporting_api/ から最新の Reporting API impressions_summary を読み込む (#84)。"""
    return _load_latest_snapshot(channel_data_dir / "analytics" / "reporting_api")


def _load_latest_snapshot(snapshot_dir: Path) -> Optional[Dict]:
    """Read the final JSON filename in one snapshot directory, if present."""
    if not snapshot_dir.exists():
        return None
    files = sorted(snapshot_dir.glob("*.json"))
    if not files:
        return None
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f)


def load_video_metadata(channel_dir: Path) -> dict:
    """Extract published video titles and dates from the newest analytics snapshot."""
    data = load_latest_analytics_snapshot(channel_dir)
    meta = {}
    for video_id, video in (data.get("video_analytics") or {}).items():
        published_at = video.get("published_at")
        if video_id and published_at:
            meta[video_id] = {"title": video.get("title", ""), "published_at": published_at}
    return meta
