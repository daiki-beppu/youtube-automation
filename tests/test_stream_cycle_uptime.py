"""utils/streaming/cycle_uptime.py の純粋計算ロジックをテストする。

要件 R10: 11h+1h サイクル稼働率 (理論 91.7% に対する実測)。
- 理論値: 22h / 24h = 0.9166...
- 実測値: actual_archives / (2 * days_in_month)
"""

from __future__ import annotations

import pytest

from youtube_automation.utils.streaming import cycle_uptime


def test_theoretical_uptime_ratio_is_22_over_24():
    """Given 1 日 22 時間配信 (11h × 2 本) / 24 時間
    When theoretical_uptime_ratio を呼ぶ
    Then 22/24 = 0.9166... が返る (order.md「理論値 91.7%」)。
    """
    assert cycle_uptime.theoretical_uptime_ratio() == pytest.approx(22 / 24)


def test_actual_uptime_ratio_full_month_30days():
    """Given 30 日の月で 60 本のアーカイブ (理論満額)
    When actual_uptime_ratio を呼ぶ
    Then 60 / (2 * 30) = 1.0 (理論を満たした稼働)。
    """
    assert cycle_uptime.actual_uptime_ratio(actual_archives=60, days_in_month=30) == pytest.approx(1.0)


def test_actual_uptime_ratio_half_month():
    """Given 30 日の月で 30 本のアーカイブ
    When actual_uptime_ratio を呼ぶ
    Then 30 / 60 = 0.5。
    """
    assert cycle_uptime.actual_uptime_ratio(actual_archives=30, days_in_month=30) == 0.5


def test_actual_uptime_ratio_zero_archives():
    """Given アーカイブ 0 本
    When actual_uptime_ratio を呼ぶ
    Then 0.0 (境界値)。
    """
    assert cycle_uptime.actual_uptime_ratio(actual_archives=0, days_in_month=30) == 0.0


def test_actual_uptime_ratio_31day_month():
    """Given 31 日の月で 62 本 (理論満額)
    When actual_uptime_ratio を呼ぶ
    Then 1.0。
    """
    assert cycle_uptime.actual_uptime_ratio(actual_archives=62, days_in_month=31) == pytest.approx(1.0)


def test_actual_uptime_ratio_28day_february():
    """Given 28 日の 2 月で 56 本
    When actual_uptime_ratio を呼ぶ
    Then 1.0。
    """
    assert cycle_uptime.actual_uptime_ratio(actual_archives=56, days_in_month=28) == pytest.approx(1.0)


def test_actual_uptime_ratio_partial():
    """Given 30 日 / 45 本 (理論の 75%)
    When actual_uptime_ratio を呼ぶ
    Then 45/60 = 0.75。
    """
    assert cycle_uptime.actual_uptime_ratio(actual_archives=45, days_in_month=30) == 0.75


def test_actual_uptime_ratio_zero_days_raises():
    """Given days_in_month=0
    When actual_uptime_ratio を呼ぶ
    Then ZeroDivisionError or ValueError (Fail Fast。フォールバック禁止)。
    """
    with pytest.raises((ZeroDivisionError, ValueError)):
        cycle_uptime.actual_uptime_ratio(actual_archives=10, days_in_month=0)
