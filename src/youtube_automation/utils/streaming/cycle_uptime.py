"""配信稼働率計算（Issue #110 / R10, ADR-0014）。

理論値: 1 日 24h 配信 / 24h = 1.0 (100%)
実測値: 24/7 デフォルトではアーカイブ数ベースの計算を行わない。
"""

from __future__ import annotations

from youtube_automation.utils.streaming import ARCHIVES_EXPECTED, THEORETICAL_HOURS_PER_DAY

_HOURS_PER_DAY = 24
_ARCHIVES_PER_DAY = 2  # ARCHIVES_EXPECTED=True 時の 1 日あたり理論アーカイブ本数


def theoretical_uptime_ratio() -> float:
    """理論稼働率を返す。24 / 24 = 1.0。"""
    return THEORETICAL_HOURS_PER_DAY / _HOURS_PER_DAY


def actual_uptime_ratio(*, actual_archives: int, days_in_month: int) -> float | None:
    """実測稼働率を返す。

    Args:
        actual_archives: その月にアーカイブされた配信本数
        days_in_month: その月の日数

    Returns:
        ARCHIVES_EXPECTED=True なら actual_archives / (2 * days_in_month)。
        ARCHIVES_EXPECTED=False なら None。

    Raises:
        ValueError: days_in_month が 0 以下の場合 (Fail Fast)
    """
    _validate_days_in_month(days_in_month)
    if not ARCHIVES_EXPECTED:
        return None
    return actual_archives / (_ARCHIVES_PER_DAY * days_in_month)


def theoretical_archive_count(*, days_in_month: int) -> int | None:
    """理論アーカイブ本数を返す。"""
    _validate_days_in_month(days_in_month)
    if not ARCHIVES_EXPECTED:
        return None
    return _ARCHIVES_PER_DAY * days_in_month


def _validate_days_in_month(days_in_month: int) -> None:
    """days_in_month の不正値を検出する。"""
    if days_in_month <= 0:
        raise ValueError(f"days_in_month must be positive, got {days_in_month}")
