"""Launch curve 分析用の DataFrame 構築ユーティリティ"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

import pandas as pd


def build_launch_curve_frame(
    daily_data: Dict,
    video_meta: Dict[str, Dict],
) -> pd.DataFrame:
    """
    永続化 JSON と動画メタから launch curve 用 DataFrame を構築する。

    Args:
        daily_data: {"rows": [{video_id, date, views, [impressions, impression_ctr]}, ...]}
            impressions / impression_ctr は動画×日次では取得不可のため欠損している場合がある。
        video_meta: {video_id: {"title": ..., "published_at": "ISO-8601"}}

    Returns:
        DataFrame with columns:
          video_id, date (datetime), published_at (datetime),
          days_since_publish (int), daily_views, cumulative_views,
          daily_impressions, ctr
    """
    rows = daily_data.get("rows", [])
    if not rows:
        return pd.DataFrame(
            columns=[
                "video_id",
                "date",
                "published_at",
                "days_since_publish",
                "daily_views",
                "cumulative_views",
                "daily_impressions",
                "ctr",
            ]
        )

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
    # impressions/CTR 列が無い場合は NaN で埋める
    if "daily_impressions" not in df.columns:
        df["daily_impressions"] = pd.NA
    if "ctr" not in df.columns:
        df["ctr"] = pd.NA

    df = df.sort_values(["video_id", "days_since_publish"])
    df["cumulative_views"] = df.groupby("video_id")["daily_views"].cumsum()

    return df[
        [
            "video_id",
            "date",
            "published_at",
            "days_since_publish",
            "daily_views",
            "cumulative_views",
            "daily_impressions",
            "ctr",
        ]
    ].reset_index(drop=True)


def load_latest_daily_snapshot(channel_data_dir: Path) -> Optional[Dict]:
    """data/analytics/daily_per_video/ から最新の JSON を読み込む"""
    daily_dir = channel_data_dir / "analytics" / "daily_per_video"
    if not daily_dir.exists():
        return None
    files = sorted(daily_dir.glob("*.json"))
    if not files:
        return None
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f)
