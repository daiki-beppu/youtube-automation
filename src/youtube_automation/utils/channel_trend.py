"""チャンネル全体トレンド分析と異常検知

既存 analytics_data_*.json の channel_analytics.daily_metrics を入力に、
日次系列の移動平均・WoW 成長率・スパイク/ディップ検知を計算する。
"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd


def build_trend_frame(daily_metrics: List[Dict]) -> pd.DataFrame:
    """daily_metrics → DataFrame with rolling means and z-scores.

    Columns:
        date (datetime), views, watch_time, subscribers_gained, subscribers_lost,
        subs_net, views_7d_ma, views_28d_ma, views_z_score
    """
    if not daily_metrics:
        return pd.DataFrame(
            columns=[
                "date",
                "views",
                "watch_time",
                "subscribers_gained",
                "subscribers_lost",
                "subs_net",
                "views_7d_ma",
                "views_28d_ma",
                "views_z_score",
            ]
        )

    df = pd.DataFrame(daily_metrics)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    for col in ("views", "watch_time", "subscribers_gained", "subscribers_lost"):
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["subs_net"] = df["subscribers_gained"] - df["subscribers_lost"]
    df["views_7d_ma"] = df["views"].rolling(window=7, min_periods=1).mean()
    df["views_28d_ma"] = df["views"].rolling(window=28, min_periods=1).mean()

    # z-score は当日を除く過去 14 日の分布に対する (今日 - 平均) / 標準偏差
    baseline_views = df["views"].shift(1)
    rolling_mean = baseline_views.rolling(window=14, min_periods=7).mean()
    rolling_std = baseline_views.rolling(window=14, min_periods=7).std()
    df["views_z_score"] = (df["views"] - rolling_mean) / rolling_std

    return df


def detect_anomalies(df: pd.DataFrame, z_threshold: float = 2.0) -> List[Dict]:
    """z-score 絶対値が閾値超えの日を spike/dip としてフラグする。"""
    if df.empty:
        return []
    anomalies = []
    for _, row in df.iterrows():
        z = float(row["views_z_score"])
        if pd.isna(z) or abs(z) < z_threshold:
            continue
        anomalies.append(
            {
                "date": str(row["date"].date()),
                "type": "spike" if z > 0 else "dip",
                "views": int(row["views"]),
                "z_score": round(z, 2),
                "baseline_7d_ma": round(float(row["views_7d_ma"]), 2),
            }
        )
    return anomalies


def _compute_week_over_week(df: pd.DataFrame) -> List[Dict]:
    """週次 (週の開始=月曜) の views 合計と前週比増減率を計算。"""
    if df.empty:
        return []
    weekly = (
        df.set_index("date")["views"]
        .resample("W-MON", label="left", closed="left")
        .agg(views="sum", days="count")
        .reset_index()
        .rename(columns={"date": "week_starting"})
    )
    weekly = weekly[weekly["days"] == 7].copy()
    weekly["delta_pct"] = weekly["views"].pct_change() * 100
    return [
        {
            "week_starting": str(r["week_starting"].date()),
            "views": int(r["views"]),
            "delta_pct": (round(float(r["delta_pct"]), 2) if pd.notna(r["delta_pct"]) else None),
        }
        for _, r in weekly.iterrows()
    ]


def _judge_trend_direction(df: pd.DataFrame) -> str:
    """直近 28日 MA と それ以前 28日 MA を比較して up/flat/down 判定。"""
    if len(df) < 56:
        return "flat"
    recent = df["views"].tail(28).mean()
    prior = df["views"].iloc[-56:-28].mean()
    if prior == 0:
        return "up" if recent > 0 else "flat"
    ratio = recent / prior
    if ratio >= 1.15:
        return "up"
    if ratio <= 0.85:
        return "down"
    return "flat"


def analyze_channel_trend(
    daily_metrics: List[Dict],
    z_threshold: float = 2.0,
) -> Dict:
    """AI 消費向けのトレンド分析結果を組み立てる。"""
    df = build_trend_frame(daily_metrics)

    if df.empty:
        return {
            "summary": {
                "period": None,
                "total_views": 0,
                "total_subs_gained": 0,
                "wow_growth_rate": None,
                "trend_direction": "flat",
            },
            "daily_series": [],
            "anomalies": [],
            "week_over_week": [],
        }

    anomalies = detect_anomalies(df, z_threshold=z_threshold)
    wow = _compute_week_over_week(df)

    latest_week_delta = None
    if wow and wow[-1]["delta_pct"] is not None:
        latest_week_delta = wow[-1]["delta_pct"]

    summary = {
        "period": {
            "start_date": str(df["date"].min().date()),
            "end_date": str(df["date"].max().date()),
            "days": len(df),
        },
        "total_views": int(df["views"].sum()),
        "total_subs_gained": int(df["subscribers_gained"].sum()),
        "total_subs_lost": int(df["subscribers_lost"].sum()),
        "avg_daily_views": round(float(df["views"].mean()), 2),
        "wow_growth_rate": latest_week_delta,
        "trend_direction": _judge_trend_direction(df),
    }

    daily_series = [
        {
            "date": str(r["date"].date()),
            "views": int(r["views"]),
            "watch_time_min": int(r["watch_time"]),
            "subs_gained": int(r["subscribers_gained"]),
            "subs_net": int(r["subs_net"]),
            "views_7d_ma": round(float(r["views_7d_ma"]), 2),
            "views_28d_ma": round(float(r["views_28d_ma"]), 2),
            "views_z_score": (
                round(float(r["views_z_score"]), 2) if pd.notna(r["views_z_score"]) else None
            ),
        }
        for _, r in df.iterrows()
    ]

    return {
        "summary": summary,
        "daily_series": daily_series,
        "anomalies": anomalies,
        "week_over_week": wow,
    }
