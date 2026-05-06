"""11h+1h サイクルの稼働率計算（Issue #110 / R10）。

理論値: 1 日 22h 配信 / 24h = 22/24 ≈ 0.9166 (91.7%)
実測値: actual_archives / (2 * days_in_month)
       (1 日 2 本のアーカイブが完走するのが理論満額。)
"""

from __future__ import annotations

from youtube_automation.utils.streaming import THEORETICAL_HOURS_PER_DAY

_HOURS_PER_DAY = 24
_ARCHIVES_PER_DAY = 2  # 11h × 2 本 = 22h


def theoretical_uptime_ratio() -> float:
    """理論稼働率を返す。22 / 24 = 0.9166...。"""
    return THEORETICAL_HOURS_PER_DAY / _HOURS_PER_DAY


def actual_uptime_ratio(*, actual_archives: int, days_in_month: int) -> float:
    """実測稼働率を返す。

    Args:
        actual_archives: その月にアーカイブされた配信本数
        days_in_month: その月の日数

    Returns:
        actual_archives / (2 * days_in_month)

    Raises:
        ValueError: days_in_month が 0 以下の場合 (Fail Fast)
    """
    if days_in_month <= 0:
        raise ValueError(f"days_in_month must be positive, got {days_in_month}")
    return actual_archives / (_ARCHIVES_PER_DAY * days_in_month)
