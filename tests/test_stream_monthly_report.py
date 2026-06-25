"""utils/streaming/monthly_report.py のユニットテスト。

要件 R8/R9/R10/R11: 月次レポート文字列を整形する純粋関数。

整形対象:
- 月間帯域消費量 (GB) と前月比
- 24/7 連続配信稼働率 (理論 100%)
- アーカイブ数ベース判定なし (24/7 デフォルト)
"""

from __future__ import annotations

import pytest

from youtube_automation.utils.streaming import monthly_report


def test_format_monthly_report_includes_year_month_header():
    """Given year=2026, month=4
    When format_monthly_report を呼ぶ
    Then "2026-04" がヘッダに含まれる。
    """
    text = monthly_report.format_monthly_report(
        year=2026,
        month=4,
        usage_gb=1188.0,
        previous_usage_gb=1100.0,
        archives=60,
        days_in_month=30,
    )
    assert "2026-04" in text


def test_format_monthly_report_includes_usage_gb_with_unit():
    """Given usage_gb=1188.0
    When format_monthly_report を呼ぶ
    Then "1188" と "GB" の両方を含む。
    """
    text = monthly_report.format_monthly_report(
        year=2026,
        month=4,
        usage_gb=1188.0,
        previous_usage_gb=1100.0,
        archives=60,
        days_in_month=30,
    )
    assert "1188" in text
    assert "GB" in text


def test_format_monthly_report_includes_previous_month_diff_with_sign():
    """Given usage_gb=1200, previous_usage_gb=1000
    When format_monthly_report を呼ぶ
    Then 前月比 +200 GB or +20% などが含まれ、上昇を示す符号 "+" が出る。
    """
    text = monthly_report.format_monthly_report(
        year=2026,
        month=4,
        usage_gb=1200.0,
        previous_usage_gb=1000.0,
        archives=60,
        days_in_month=30,
    )
    assert "+" in text
    # 前月比文言（"前月比" もしくは "前月" / "diff"）
    assert ("前月" in text) or ("diff" in text.lower())


def test_format_monthly_report_includes_negative_previous_month_diff():
    """Given usage_gb=900, previous_usage_gb=1000 (減少)
    When format_monthly_report を呼ぶ
    Then "-" 符号付きで前月比が出る。
    """
    text = monthly_report.format_monthly_report(
        year=2026,
        month=4,
        usage_gb=900.0,
        previous_usage_gb=1000.0,
        archives=60,
        days_in_month=30,
    )
    assert "-" in text


def test_format_monthly_report_handles_no_previous_month():
    """Given previous_usage_gb=None (初月でデータ無し)
    When format_monthly_report を呼ぶ
    Then 例外を出さず、前月比箇所には N/A 等の表記が入る。
    """
    text = monthly_report.format_monthly_report(
        year=2026,
        month=4,
        usage_gb=1200.0,
        previous_usage_gb=None,
        archives=60,
        days_in_month=30,
    )
    assert "1200" in text
    assert "前月比: N/A (前月データなし)" in text


def test_format_monthly_report_skips_archive_based_actual_uptime():
    """Given ARCHIVES_EXPECTED=False
    When format_monthly_report を呼ぶ
    Then 実測稼働率 N/A と理論 100.0% の両方を含む。
    """
    text = monthly_report.format_monthly_report(
        year=2026,
        month=4,
        usage_gb=900.0,
        previous_usage_gb=900.0,
        archives=45,
        days_in_month=30,
    )
    assert "稼働率 (24/7 連続配信): 実測 N/A / 理論 100.0%" in text


def test_format_monthly_report_skips_archive_count_line_when_archives_are_not_expected():
    """Given ARCHIVES_EXPECTED=False
    When format_monthly_report を呼ぶ
    Then 実測アーカイブ件数には依存しない。
    """
    text = monthly_report.format_monthly_report(
        year=2026,
        month=4,
        usage_gb=1188.0,
        previous_usage_gb=1100.0,
        archives=None,
        days_in_month=30,
    )
    assert "アーカイブ数ベース判定なし" in text
    assert "アーカイブ件数: 実測" not in text


def test_format_monthly_report_includes_quota_percentage():
    """Given usage_gb=1638.4 (= 80%), quota=2048
    When format_monthly_report を呼ぶ
    Then "80%" or "80.0%" or 0.80 比率が読み取れる。
    """
    text = monthly_report.format_monthly_report(
        year=2026,
        month=4,
        usage_gb=1638.4,
        previous_usage_gb=1500.0,
        archives=60,
        days_in_month=30,
    )
    assert "80" in text
    assert "%" in text


def test_format_monthly_report_returns_str():
    """Given 通常入力
    When format_monthly_report を呼ぶ
    Then str を返す (Discord webhook の content に流せる)。
    """
    text = monthly_report.format_monthly_report(
        year=2026,
        month=4,
        usage_gb=1188.0,
        previous_usage_gb=1100.0,
        archives=60,
        days_in_month=30,
    )
    assert isinstance(text, str)
    assert len(text) > 0


def test_format_monthly_report_archives_expected_true_includes_uptime_and_count(
    monkeypatch,
):
    """Given ARCHIVES_EXPECTED=True, archives=45, days_in_month=30
    When format_monthly_report を呼ぶ
    Then 実測稼働率と理論稼働率が数値で表示され、アーカイブ件数行を含む。
    """
    import youtube_automation.utils.streaming as streaming_pkg
    import youtube_automation.utils.streaming.cycle_uptime as cycle_mod

    monkeypatch.setattr(streaming_pkg, "ARCHIVES_EXPECTED", True)
    monkeypatch.setattr(cycle_mod, "ARCHIVES_EXPECTED", True)

    text = monthly_report.format_monthly_report(
        year=2026,
        month=6,
        usage_gb=1500.0,
        previous_usage_gb=1400.0,
        archives=45,
        days_in_month=30,
    )
    # 実測稼働率が N/A ではなく数値 (%) で表示される
    assert "実測 N/A" not in text
    assert "実測" in text
    assert "理論 100.0%" in text
    # アーカイブ件数行が含まれる
    assert "アーカイブ件数: 実測 45 本 / 理論 60 本" in text


def test_format_monthly_report_archives_expected_true_archives_none_raises(
    monkeypatch,
):
    """Given ARCHIVES_EXPECTED=True, archives=None
    When format_monthly_report を呼ぶ
    Then ValueError が送出される。
    """
    import youtube_automation.utils.streaming as streaming_pkg
    import youtube_automation.utils.streaming.cycle_uptime as cycle_mod

    monkeypatch.setattr(streaming_pkg, "ARCHIVES_EXPECTED", True)
    monkeypatch.setattr(cycle_mod, "ARCHIVES_EXPECTED", True)

    with pytest.raises(ValueError, match="archives is required"):
        monthly_report.format_monthly_report(
            year=2026,
            month=6,
            usage_gb=1500.0,
            previous_usage_gb=1400.0,
            archives=None,
            days_in_month=30,
        )
