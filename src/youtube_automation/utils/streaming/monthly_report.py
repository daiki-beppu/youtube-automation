"""月次レポート整形（Issue #110 / R8, R9, R10, R11）。

純粋関数 `format_monthly_report` を公開する。Discord webhook の `content` 文字列に
そのまま流せる平文テキストを返す。
"""

from __future__ import annotations

from youtube_automation.utils.streaming import (
    MONTHLY_QUOTA_GB,
    THRESHOLD_RATIO,
)
from youtube_automation.utils.streaming.cycle_uptime import (
    actual_uptime_ratio,
    theoretical_archive_count,
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


def _format_actual_uptime(actual_uptime: float | None) -> str:
    """実測稼働率の表示値を返す。"""
    if actual_uptime is None:
        return "N/A"
    return f"{actual_uptime * 100:.1f}%"


def _format_archive_count(archives: int | None, theoretical_archives: int | None) -> str:
    """アーカイブ件数の表示行を返す。"""
    if theoretical_archives is None:
        return "アーカイブ数ベース判定なし"
    if archives is None:
        raise ValueError("archives is required when archive-based reporting is enabled")
    return f"アーカイブ件数: 実測 {archives} 本 / 理論 {theoretical_archives} 本"


def format_monthly_report(
    *,
    year: int,
    month: int,
    usage_gb: float,
    previous_usage_gb: float | None,
    archives: int | None,
    days_in_month: int,
) -> str:
    """月次レポートテキストを整形する。

    Args:
        year: 対象年
        month: 対象月 (1-12)
        usage_gb: 月間帯域消費量 (GB)
        previous_usage_gb: 前月の帯域消費量 (GB)。データ無しなら None
        archives: 月間アーカイブ本数 (実測)。アーカイブ数ベース判定なしなら None
        days_in_month: 対象月の日数

    Returns:
        Discord webhook 等にそのまま流せる平文テキスト
    """
    quota_pct = (usage_gb / MONTHLY_QUOTA_GB) * 100
    threshold_pct = int(THRESHOLD_RATIO * 100)
    theoretical_archives = theoretical_archive_count(days_in_month=days_in_month)
    actual_uptime = None
    if theoretical_archives is not None:
        if archives is None:
            raise ValueError("archives is required when archive-based reporting is enabled")
        actual_uptime = actual_uptime_ratio(actual_archives=archives, days_in_month=days_in_month)
    theoretical_uptime = theoretical_uptime_ratio() * 100

    lines = [
        f"# 月次帯域レポート {year:04d}-{month:02d}",
        "",
        f"帯域消費量: {usage_gb:.1f} GB / {MONTHLY_QUOTA_GB} GB ({quota_pct:.1f}%)",
        f"  - アラート閾値: {threshold_pct}%",
        f"  - {_format_diff_gb(usage_gb, previous_usage_gb)}",
        "",
        f"稼働率 (24/7 連続配信): 実測 {_format_actual_uptime(actual_uptime)} / 理論 {theoretical_uptime:.1f}%",
        _format_archive_count(archives, theoretical_archives),
    ]
    return "\n".join(lines)
