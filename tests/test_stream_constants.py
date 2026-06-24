"""utils/streaming/__init__.py の定数集中をテストする。

計画 §「定数集中」: MONTHLY_QUOTA_GB / THRESHOLD_RATIO / THEORETICAL_BITRATE_MBPS /
THEORETICAL_HOURS_PER_DAY / THEORETICAL_ARCHIVES_PER_MONTH を package __init__ に集約し、
CLI / レポート / テストで重複定義しないこと。
"""

from __future__ import annotations

from youtube_automation.utils import streaming


def test_monthly_quota_gb_is_2048():
    """Given Vultr vc2-1c-2gb プラン (2 TB / 月)
    When MONTHLY_QUOTA_GB を引く
    Then 2048 (= 2 TB を GB 換算した値) で固定されている。
    """
    assert streaming.MONTHLY_QUOTA_GB == 2048


def test_threshold_ratio_is_080():
    """Given order.md「80% 到達時のアラート (1.6 TB)」
    When THRESHOLD_RATIO を引く
    Then 0.80 で固定されている。
    """
    assert streaming.THRESHOLD_RATIO == 0.80


def test_theoretical_bitrate_is_4_mbps():
    """Given order.md「ビットレート: 4 Mbps」
    When THEORETICAL_BITRATE_MBPS を引く
    Then 4 で固定されている。
    """
    assert streaming.THEORETICAL_BITRATE_MBPS == 4


def test_archive_mode_constants_are_not_public_api():
    """Given Terraform の配信サイクル追加は Python 公開 API の変更対象外
    When streaming 定数を引く
    Then ARCHIVE_MODE_* の公開定数を追加していない。
    """
    assert not hasattr(streaming, "ARCHIVE_MODE_STREAM_HOURS")
    assert not hasattr(streaming, "ARCHIVE_MODE_BREAK_HOURS")
    assert not hasattr(streaming, "ARCHIVE_MODE_ARCHIVES_PER_DAY")


def test_theoretical_hours_per_day_is_22():
    """Given order.md「1 日の配信時間: 22 時間 (11h × 2 本)」
    When THEORETICAL_HOURS_PER_DAY を引く
    Then 22 で固定されている。
    """
    assert streaming.THEORETICAL_HOURS_PER_DAY == 22


def test_theoretical_archives_per_month_is_60():
    """Given order.md「アーカイブ件数 (理論値 60 本/月)」
    When THEORETICAL_ARCHIVES_PER_MONTH を引く
    Then 60 で固定されている。
    """
    assert streaming.THEORETICAL_ARCHIVES_PER_MONTH == 60
