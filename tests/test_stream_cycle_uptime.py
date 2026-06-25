"""utils/streaming/cycle_uptime.py の純粋計算ロジックをテストする。

要件 R10 / ADR-0014: 24/7 連続配信の稼働率。
- 理論値: 24h / 24h = 1.0
- 実測値: ARCHIVES_EXPECTED=False ではアーカイブ数ベース計算を行わない
"""

from __future__ import annotations

import pytest

from youtube_automation.utils.streaming import cycle_uptime


def test_theoretical_uptime_ratio_is_24_over_24():
    """Given 1 日 24 時間配信 / 24 時間
    When theoretical_uptime_ratio を呼ぶ
    Then 24/24 = 1.0 が返る。
    """
    assert cycle_uptime.theoretical_uptime_ratio() == pytest.approx(1.0)


def test_actual_uptime_ratio_skips_archive_based_calculation_by_default():
    """Given ARCHIVES_EXPECTED=False
    When actual_uptime_ratio を呼ぶ
    Then アーカイブ本数ベースの実測稼働率は None になる。
    """
    assert cycle_uptime.actual_uptime_ratio(actual_archives=60, days_in_month=30) is None


def test_actual_uptime_ratio_validates_days_when_archives_are_not_expected():
    """Given ARCHIVES_EXPECTED=False かつ days_in_month=0
    When actual_uptime_ratio を呼ぶ
    Then ValueError を送出する。
    """
    with pytest.raises(ValueError):
        cycle_uptime.actual_uptime_ratio(actual_archives=10, days_in_month=0)


@pytest.mark.parametrize(
    ("archives", "days_in_month", "expected"),
    [
        (60, 30, 1.0),
        (30, 30, 0.5),
        (0, 30, 0.0),
        (62, 31, 1.0),
        (56, 28, 1.0),
        (45, 30, 0.75),
    ],
)
def test_actual_uptime_ratio_uses_archive_count_when_archives_are_expected(
    monkeypatch: pytest.MonkeyPatch,
    archives: int,
    days_in_month: int,
    expected: float,
):
    """Given ARCHIVES_EXPECTED=True
    When actual_uptime_ratio を呼ぶ
    Then actual_archives / (2 * days_in_month) を返す。
    """
    monkeypatch.setattr(cycle_uptime, "ARCHIVES_EXPECTED", True)

    assert cycle_uptime.actual_uptime_ratio(
        actual_archives=archives,
        days_in_month=days_in_month,
    ) == pytest.approx(expected)


def test_actual_uptime_ratio_zero_days_raises_when_archives_are_expected(monkeypatch: pytest.MonkeyPatch):
    """Given ARCHIVES_EXPECTED=True かつ days_in_month=0
    When actual_uptime_ratio を呼ぶ
    Then ValueError を送出する。
    """
    monkeypatch.setattr(cycle_uptime, "ARCHIVES_EXPECTED", True)

    with pytest.raises(ValueError):
        cycle_uptime.actual_uptime_ratio(actual_archives=10, days_in_month=0)


def test_theoretical_archive_count_returns_none_by_default():
    """Given ARCHIVES_EXPECTED=False
    When theoretical_archive_count を呼ぶ
    Then 理論アーカイブ本数は None になる。
    """
    assert cycle_uptime.theoretical_archive_count(days_in_month=30) is None


def test_theoretical_archive_count_uses_days_when_archives_are_expected(monkeypatch: pytest.MonkeyPatch):
    """Given ARCHIVES_EXPECTED=True
    When theoretical_archive_count を呼ぶ
    Then 2 * days_in_month を返す。
    """
    monkeypatch.setattr(cycle_uptime, "ARCHIVES_EXPECTED", True)

    assert cycle_uptime.theoretical_archive_count(days_in_month=31) == 62
