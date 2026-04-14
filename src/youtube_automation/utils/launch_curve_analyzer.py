"""Launch curve ベンチマーク計算と判定ロジック"""

from __future__ import annotations

from typing import Dict, Optional

import pandas as pd


def compute_benchmark(
    df: pd.DataFrame,
    metric: str = "cumulative_views",
    exclude_video_id: Optional[str] = None,
) -> pd.DataFrame:
    """
    各 days_since_publish 値で過去動画の percentile ベンチマークを計算する。

    Returns:
        DataFrame: days_since_publish, p10, p25, p50, p75, p90, sample_size
    """
    source = df if exclude_video_id is None else df[df["video_id"] != exclude_video_id]

    grouped = source.groupby("days_since_publish")[metric]
    result = grouped.agg(
        p10=lambda s: s.quantile(0.10),
        p25=lambda s: s.quantile(0.25),
        p50=lambda s: s.quantile(0.50),
        p75=lambda s: s.quantile(0.75),
        p90=lambda s: s.quantile(0.90),
        sample_size="count",
    ).reset_index()
    return result


def judge_video_vs_benchmark(
    df: pd.DataFrame,
    benchmark: pd.DataFrame,
    video_id: str,
    at_day: int,
    metric: str = "cumulative_views",
) -> Dict:
    """対象動画の指定日齢時点の値をベンチマークと比較して判定する。"""
    target = df[(df["video_id"] == video_id) & (df["days_since_publish"] == at_day)]
    if target.empty:
        return {"error": f"video {video_id} has no data at day {at_day}"}

    value = float(target[metric].iloc[0])
    bench_row = benchmark[benchmark["days_since_publish"] == at_day]
    if bench_row.empty or bench_row["sample_size"].iloc[0] < 3:
        return {
            "value": value,
            "benchmark_median": None,
            "ratio_vs_median": None,
            "quartile_label": "サンプル不足",
            "sample_size": int(bench_row["sample_size"].iloc[0]) if not bench_row.empty else 0,
        }

    p25 = float(bench_row["p25"].iloc[0])
    p50 = float(bench_row["p50"].iloc[0])
    p75 = float(bench_row["p75"].iloc[0])

    if value >= p75:
        label = "上位25%"
    elif value >= p50:
        label = "中央値〜上位25%"
    elif value >= p25:
        label = "下位25%〜中央値"
    else:
        label = "下位25%"

    return {
        "value": value,
        "benchmark_median": p50,
        "benchmark_p25": p25,
        "benchmark_p75": p75,
        "ratio_vs_median": value / p50 if p50 > 0 else None,
        "quartile_label": label,
        "sample_size": int(bench_row["sample_size"].iloc[0]),
    }
