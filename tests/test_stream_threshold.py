"""utils/streaming/threshold.py の純粋計算ロジックをテストする。

要件 R6: 80% 到達 (1.6 TB) アラート判定。
"""

from __future__ import annotations

import pytest

from youtube_automation.utils.streaming import threshold


def test_threshold_gb_is_quota_times_ratio():
    """Given quota_gb=2048, ratio=0.80
    When threshold_gb を計算する
    Then 2048 * 0.80 = 1638.4 GB が返る。
    """
    assert threshold.threshold_gb(quota_gb=2048, ratio=0.80) == pytest.approx(1638.4)


def test_threshold_gb_general_formula():
    """Given 任意の quota_gb と ratio
    When threshold_gb を呼ぶ
    Then quota_gb * ratio がそのまま返る (純粋関数)。
    """
    assert threshold.threshold_gb(quota_gb=1000, ratio=0.5) == 500.0
    assert threshold.threshold_gb(quota_gb=3072, ratio=0.9) == pytest.approx(2764.8)


def test_is_over_threshold_true_at_boundary():
    """Given usage_gb がちょうど閾値 1638.4
    When is_over_threshold を呼ぶ
    Then True (>= で判定する)。
    """
    assert threshold.is_over_threshold(usage_gb=1638.4, quota_gb=2048, ratio=0.80) is True


def test_is_over_threshold_false_just_under():
    """Given usage_gb が閾値直下 (1638.3 GB)
    When is_over_threshold を呼ぶ
    Then False。
    """
    assert threshold.is_over_threshold(usage_gb=1638.3, quota_gb=2048, ratio=0.80) is False


def test_is_over_threshold_true_at_quota():
    """Given usage_gb がクォータ満了 (2048 GB)
    When is_over_threshold を呼ぶ
    Then True。
    """
    assert threshold.is_over_threshold(usage_gb=2048, quota_gb=2048, ratio=0.80) is True


def test_is_over_threshold_false_when_zero():
    """Given usage_gb=0
    When is_over_threshold を呼ぶ
    Then False (境界値)。
    """
    assert threshold.is_over_threshold(usage_gb=0, quota_gb=2048, ratio=0.80) is False


def test_is_over_threshold_uses_passed_quota_not_constant():
    """Given quota_gb=1024, ratio=0.5 (閾値=512 GB)
    When usage_gb=600 で呼ぶ
    Then True (内部で MONTHLY_QUOTA_GB を再 import しないこと)。
    """
    assert threshold.is_over_threshold(usage_gb=600, quota_gb=1024, ratio=0.5) is True
    assert threshold.is_over_threshold(usage_gb=500, quota_gb=1024, ratio=0.5) is False
