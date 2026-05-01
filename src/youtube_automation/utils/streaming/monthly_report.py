"""月次レポート整形（Issue #110 / R8, R9, R10, R11）。

純粋関数 `format_monthly_report` を公開する。Discord webhook の `content` 文字列に
そのまま流せる平文テキストを返す。
"""

from __future__ import annotations

from youtube_automation.utils.streaming import (
    MONTHLY_QUOTA_GB,
    THEORETICAL_ARCHIVES_PER_MONTH,
    THRESHOLD_RATIO,
)
from youtube_automation.utils.streaming.cycle_uptime import (
    actual_uptime_ratio,
    theoretical_uptime_ratio,
)


def _format_diff_gb(usage_gb: float, previous_usage_gb: float | None) -> str:
    """前月比文言を返す。"""
    if previous_usage_gb is None:
        return "前月比: N/A (前月データなし)"
    diff = usage_gb - previous_usage_gb
    if previous_usage_gb > 0:
        pct = diff / previous_usage_gb * 100
        return f"前月比: {diff:+.1f} GB ({pct:+.1f}%)"
    return f"前月比: {diff:+.1f} GB"


def format_monthly_report(
    *,
    year: int,
    month: int,
    usage_gb: float,
    previous_usage_gb: float | None,
    archives: int,
    days_in_month: int,
) -> str:
    """月次レポートテキストを整形する。

    Args:
        year: 対象年
        month: 対象月 (1-12)
        usage_gb: 月間帯域消費量 (GB)
        previous_usage_gb: 前月の帯域消費量 (GB)。データ無しなら None
        archives: 月間アーカイブ本数 (実測)
        days_in_month: 対象月の日数

    Returns:
        Discord webhook 等にそのまま流せる平文テキスト
    """
    quota_pct = (usage_gb / MONTHLY_QUOTA_GB) * 100
    threshold_pct = int(THRESHOLD_RATIO * 100)
    actual_uptime = actual_uptime_ratio(actual_archives=archives, days_in_month=days_in_month) * 100
    theoretical_uptime = theoretical_uptime_ratio() * 100

    lines = [
        f"# 月次帯域レポート {year:04d}-{month:02d}",
        "",
        f"帯域消費量: {usage_gb:.1f} GB / {MONTHLY_QUOTA_GB} GB ({quota_pct:.1f}%)",
        f"  - アラート閾値: {threshold_pct}%",
        f"  - {_format_diff_gb(usage_gb, previous_usage_gb)}",
        "",
        f"稼働率 (11h+1h サイクル): 実測 {actual_uptime:.1f}% / 理論 {theoretical_uptime:.1f}%",
        f"アーカイブ件数: 実測 {archives} 本 / 理論 {THEORETICAL_ARCHIVES_PER_MONTH} 本",
    ]
    return "\n".join(lines)
