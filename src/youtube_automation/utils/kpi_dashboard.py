"""成長 KPI 定点ビュー — スナップショット横断のレバー別週次推移

data/analytics_data_*.json 群を時系列に読み、views / インプレッション / CTR /
平均視聴維持率 / 登録者純増の週次推移（前週比付き）を組み立てる。

- daily_metrics は channel_analytics.daily_metrics から、Imp/CTR は
  reporting_api.impressions_summary.per_day から復元する
- 同一日付が複数スナップショットに現れた場合は後（新しいスナップショット）勝ち
- Reporting API の保持期間（60 日）を超えた過去分もスナップショットに残って
  いれば時系列に含める
- スナップショットが存在しない週は欠測として明示し、ゼロや直前値で補間しない
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

SCHEMA_VERSION = 1

MULTI_SNAPSHOT_NOTE = (
    "時系列生成には複数スナップショットが必要です。"
    "`yt-analytics` を定期実行して data/analytics_data_*.json を蓄積してください。"
)


def merge_snapshot_series(snapshots: List[Dict]) -> Dict[str, List[Dict]]:
    """スナップショット群を日付キーでマージし、日次系列 2 本を返す。

    snapshots は古い順に渡すこと。同一日付は後のスナップショットの値で上書きする。

    Returns:
        {"daily_metrics": [...], "impressions_daily": [...]} （いずれも日付昇順）
    """
    daily_by_date: Dict[str, Dict] = {}
    impressions_by_date: Dict[str, Dict] = {}

    for snapshot in snapshots:
        channel_analytics = snapshot.get("channel_analytics") or {}
        for row in channel_analytics.get("daily_metrics") or []:
            date = row.get("date")
            if date:
                daily_by_date[date] = row

        reporting = snapshot.get("reporting_api") or {}
        summary = reporting.get("impressions_summary") or {}
        for row in summary.get("per_day") or []:
            date = row.get("date")
            if date:
                impressions_by_date[date] = row

    return {
        "daily_metrics": [daily_by_date[d] for d in sorted(daily_by_date)],
        "impressions_daily": [impressions_by_date[d] for d in sorted(impressions_by_date)],
    }


def _round_or_none(value, digits: int = 2) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _pct_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """前週比（変化率 %）。どちらかが欠測、または前週が 0 のときは None。"""
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


def _pts_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """率系 KPI の前週差（ポイント）。どちらかが欠測なら None。"""
    if current is None or previous is None:
        return None
    return round(current - previous, 2)


def _weekly_daily_frame(daily_metrics: List[Dict]) -> pd.DataFrame:
    df = pd.DataFrame(daily_metrics)
    df["date"] = pd.to_datetime(df["date"])
    for col in ("views", "subscribers_gained", "subscribers_lost", "avg_view_percentage"):
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["views"] = df["views"].fillna(0)
    df["subs_net"] = df["subscribers_gained"].fillna(0) - df["subscribers_lost"].fillna(0)
    df["weighted_avp"] = df["avg_view_percentage"] * df["views"]
    grouped = df.set_index("date").resample("W-MON", label="left", closed="left")
    weekly = grouped.agg(
        views=("views", "sum"),
        subs_net=("subs_net", "sum"),
        weighted_avp=("weighted_avp", "sum"),
        avp_plain_mean=("avg_view_percentage", "mean"),
        days_covered=("views", "count"),
    )
    # views 加重平均。週内 views が 0 のときは単純平均へフォールバック
    weekly["avg_view_percentage"] = weekly.apply(
        lambda r: (r["weighted_avp"] / r["views"]) if r["views"] > 0 else r["avp_plain_mean"],
        axis=1,
    )
    return weekly.drop(columns=["weighted_avp", "avp_plain_mean"])


def _weekly_impressions_frame(impressions_daily: List[Dict]) -> pd.DataFrame:
    df = pd.DataFrame(impressions_daily)
    df["date"] = pd.to_datetime(df["date"])
    df["impressions"] = pd.to_numeric(df.get("impressions"), errors="coerce").fillna(0)
    df["ctr_percentage"] = pd.to_numeric(df.get("ctr_percentage"), errors="coerce")
    df["weighted_ctr"] = df["ctr_percentage"] * df["impressions"]
    grouped = df.set_index("date").resample("W-MON", label="left", closed="left")
    weekly = grouped.agg(
        impressions=("impressions", "sum"),
        weighted_ctr=("weighted_ctr", "sum"),
        impressions_days_covered=("impressions", "count"),
    )
    # インプレッション加重平均 CTR（reporting_api の集計方式と揃える）
    weekly["ctr_percentage"] = weekly.apply(
        lambda r: (r["weighted_ctr"] / r["impressions"]) if r["impressions"] > 0 else pd.NA,
        axis=1,
    )
    return weekly.drop(columns=["weighted_ctr"])


def build_weekly_kpi(
    daily_metrics: List[Dict],
    impressions_daily: List[Dict],
) -> List[Dict]:
    """マージ済み日次系列 → レバー別 KPI の週次推移（前週比付き）。

    期間全体（両系列の union）の週をすべて行として出し、日次データが 1 日も
    ない週は欠測（views 等 = None, missing=True）として明示する。
    """
    has_daily = bool(daily_metrics)
    has_impressions = bool(impressions_daily)
    if not has_daily and not has_impressions:
        return []

    frames = []
    if has_daily:
        frames.append(_weekly_daily_frame(daily_metrics))
    if has_impressions:
        frames.append(_weekly_impressions_frame(impressions_daily))

    merged = pd.concat(frames, axis=1, sort=True) if len(frames) > 1 else frames[0]
    # 期間内の全週を行として出す（欠測週も行にする）
    full_index = pd.date_range(merged.index.min(), merged.index.max(), freq="W-MON")
    if len(full_index) > 0:
        merged = merged.reindex(merged.index.union(full_index))

    rows: List[Dict] = []
    previous: Optional[Dict] = None
    for week_start, r in merged.iterrows():
        days_covered = int(r["days_covered"]) if has_daily and pd.notna(r.get("days_covered")) else 0
        imp_days = (
            int(r["impressions_days_covered"]) if has_impressions and pd.notna(r.get("impressions_days_covered")) else 0
        )
        daily_missing = days_covered == 0
        impressions_missing = imp_days == 0

        row: Dict = {
            "week_starting": str(week_start.date()),
            "days_covered": days_covered,
            "impressions_days_covered": imp_days,
            "missing": daily_missing and impressions_missing,
            "views": None if daily_missing else int(r["views"]),
            "avg_view_percentage": None if daily_missing else _round_or_none(r["avg_view_percentage"]),
            "subs_net": None if daily_missing else int(r["subs_net"]),
            "impressions": None if impressions_missing else int(r["impressions"]),
            "ctr_percentage": None if impressions_missing else _round_or_none(r["ctr_percentage"]),
        }

        prev = previous or {}
        row["views_delta_pct"] = _pct_change(row["views"], prev.get("views"))
        row["impressions_delta_pct"] = _pct_change(row["impressions"], prev.get("impressions"))
        row["ctr_delta_pts"] = _pts_change(row["ctr_percentage"], prev.get("ctr_percentage"))
        row["avg_view_percentage_delta_pts"] = _pts_change(row["avg_view_percentage"], prev.get("avg_view_percentage"))
        row["subs_net_delta"] = (
            row["subs_net"] - prev["subs_net"]
            if row["subs_net"] is not None and prev.get("subs_net") is not None
            else None
        )

        rows.append(row)
        previous = row

    return rows


def analyze_kpi_dashboard(snapshots: List[Dict]) -> Dict:
    """スナップショット群 → 成長 KPI 定点ビュー（AI / レポート消費向け）。"""
    merged = merge_snapshot_series(snapshots)
    weekly = build_weekly_kpi(merged["daily_metrics"], merged["impressions_daily"])

    notes: List[str] = []
    if len(snapshots) <= 1:
        notes.append(MULTI_SNAPSHOT_NOTE)

    daily_dates = [row["date"] for row in merged["daily_metrics"]]
    impression_dates = [row["date"] for row in merged["impressions_daily"]]
    all_dates = sorted(set(daily_dates) | set(impression_dates))

    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_count": len(snapshots),
        "period": {
            "start_date": all_dates[0] if all_dates else None,
            "end_date": all_dates[-1] if all_dates else None,
            "daily_metric_days": len(daily_dates),
            "impression_days": len(impression_dates),
        },
        "weekly_kpi": weekly,
        "notes": notes,
    }


def _fmt(value, suffix: str = "", signed: bool = False) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        text = f"{value:+.2f}" if signed else f"{value:.2f}"
    else:
        text = f"{value:+,}" if signed else f"{value:,}"
    return f"{text}{suffix}"


def render_markdown(analysis: Dict) -> str:
    """定点ビューを Markdown レポートとして描画する。"""
    period = analysis["period"]
    lines = [
        "# 成長 KPI 定点ビュー（週次推移）",
        "",
        f"- 期間: {period['start_date']} 〜 {period['end_date']}",
        f"- スナップショット数: {analysis['snapshot_count']}",
        "- 日次カバレッジ: "
        f"daily_metrics {period['daily_metric_days']} 日 / impressions {period['impression_days']} 日",
        "",
    ]
    for note in analysis["notes"]:
        lines.append(f"> ⚠️ {note}")
        lines.append("")

    weekly = analysis["weekly_kpi"]
    if not weekly:
        lines.append("週次データがありません。")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| 週 (月曜開始) | Views | Δ% | Imp | Δ% | CTR % | Δpt | 維持率 % | Δpt | 登録純増 | Δ | 日数 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for w in weekly:
        cells = [
            w["week_starting"] + (" (欠測)" if w["missing"] else ""),
            _fmt(w["views"]),
            _fmt(w["views_delta_pct"], "%", signed=True),
            _fmt(w["impressions"]),
            _fmt(w["impressions_delta_pct"], "%", signed=True),
            _fmt(w["ctr_percentage"]),
            _fmt(w["ctr_delta_pts"], signed=True),
            _fmt(w["avg_view_percentage"]),
            _fmt(w["avg_view_percentage_delta_pts"], signed=True),
            _fmt(w["subs_net"]),
            _fmt(w["subs_net_delta"], signed=True),
            f"{w['days_covered']}/{w['impressions_days_covered']}",
        ]
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(
        [
            "",
            "凡例: `—` は欠測（補間なし）。日数列は `daily_metrics 日数 / impressions 日数`。",
            "CTR はインプレッション加重平均、維持率は views 加重平均。",
        ]
    )
    return "\n".join(lines) + "\n"
