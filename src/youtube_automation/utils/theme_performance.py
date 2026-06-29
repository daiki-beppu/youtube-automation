"""テーマ/コレクション別 launch curve 比較分析

Phase 1 の launch_curve_data の DataFrame を再利用し、
config/channel/content.json::tags.themes のキーワードでテーマ分類、
各テーマの平均曲線とピーク日齢を AI 消費向けに集計する。
"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd


def classify_videos_by_theme(
    video_meta: Dict[str, Dict],
    theme_keywords: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    """タイトルに含まれるキーワードで動画をテーマ分類する。

    Args:
        video_meta: {video_id: {"title": ..., "published_at": ...}}
        theme_keywords: {theme_name: [keyword1, keyword2, ...]}

    Returns:
        {theme_name: [video_id, ...]}. マッチしない動画は "other" に集約。
    """
    result: Dict[str, List[str]] = {theme: [] for theme in theme_keywords}
    result["other"] = []

    for vid, meta in video_meta.items():
        title_lower = (meta.get("title") or "").lower()
        matched = False
        for theme, keywords in theme_keywords.items():
            search_terms = [theme.lower()] + [k.lower() for k in keywords]
            if any(term in title_lower for term in search_terms):
                result[theme].append(vid)
                matched = True
                break
        if not matched:
            result["other"].append(vid)

    if not result["other"]:
        del result["other"]
    return result


def analyze_theme_performance(
    df: pd.DataFrame,
    theme_video_map: Dict[str, List[str]],
    peak_days: tuple = (3, 7, 30),
) -> Dict:
    """各テーマの平均 launch curve とピーク日齢を集計。

    Args:
        df: launch_curve_data.build_launch_curve_frame の出力
        theme_video_map: {theme: [video_id, ...]}
        peak_days: 比較の基準日齢タプル

    Returns:
        {themes: [...], best_theme_by_initial_velocity, best_theme_by_long_tail}
    """
    themes_out: List[Dict] = []

    for theme, vids in theme_video_map.items():
        if not vids:
            continue
        theme_df = df[df["video_id"].isin(vids)]
        if theme_df.empty:
            continue

        # 各 day の平均 cumulative_views
        mean_by_day = (
            theme_df.groupby("days_since_publish")["cumulative_views"]
            .mean()
            .reset_index()
            .rename(columns={"cumulative_views": "mean_cumulative_views"})
        )
        mean_curve = [
            {
                "day": int(r["days_since_publish"]),
                "mean_cumulative_views": round(float(r["mean_cumulative_views"]), 2),
                "sample_size": int(len(theme_df[theme_df["days_since_publish"] == r["days_since_publish"]])),
            }
            for _, r in mean_by_day.iterrows()
        ]

        peaks = {}
        for day in peak_days:
            row = mean_by_day[mean_by_day["days_since_publish"] == day]
            peaks[f"day{day}_mean"] = round(float(row["mean_cumulative_views"].iloc[0]), 2) if not row.empty else None

        themes_out.append(
            {
                "theme": theme,
                "video_count": len(vids),
                "total_cumulative_views": int(theme_df.groupby("video_id")["cumulative_views"].max().sum()),
                "mean_curve": mean_curve,
                **peaks,
            }
        )

    def _best(key):
        valid = [t for t in themes_out if t.get(key) is not None and t["theme"] != "other"]
        if not valid:
            return None
        return max(valid, key=lambda t: t[key])["theme"]

    # 初速は day3、ロングテールは最大の peak_days
    velocity_key = f"day{peak_days[0]}_mean"
    longtail_key = f"day{max(peak_days)}_mean"

    return {
        "themes": themes_out,
        "peak_days": list(peak_days),
        "best_theme_by_initial_velocity": _best(velocity_key),
        "best_theme_by_long_tail": _best(longtail_key),
    }
