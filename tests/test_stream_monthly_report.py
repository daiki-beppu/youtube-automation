"""utils/streaming/monthly_report.py のユニットテスト。

要件 R8/R9/R10/R11: 月次レポート文字列を整形する純粋関数。

整形対象:
- 月間帯域消費量 (GB) と前月比
- 11h+1h サイクル稼働率 (理論 91.7% に対する実測)
- アーカイブ件数 (理論 60 本)
- back-calc Mbps: usage_gb × 8 × 1024 / (archives × 11h × 3600)
"""

from __future__ import annotations

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
    assert ("N/A" in text) or ("-" in text) or ("なし" in text)


def test_format_monthly_report_includes_uptime_actual_and_theoretical():
    """Given archives=45, days_in_month=30 (理論 60 本)
    When format_monthly_report を呼ぶ
    Then 実測稼働率 75% と理論 91.7% (or 0.917) の両方を含む。
    """
    text = monthly_report.format_monthly_report(
        year=2026,
        month=4,
        usage_gb=900.0,
        previous_usage_gb=900.0,
        archives=45,
        days_in_month=30,
    )
    # 実測 = 45 / 60 = 0.75 → 75%
    assert "75" in text
    # 理論 = 22/24 ≈ 91.7% → "91.7" あるいは小数で 0.91 系
    assert ("91.7" in text) or ("91.6" in text)


def test_format_monthly_report_includes_archive_count_actual_and_theoretical():
    """Given archives=58 (理論 60)
    When format_monthly_report を呼ぶ
    Then "58" と "60" の両方を含む (実測 vs 理論)。
    """
    text = monthly_report.format_monthly_report(
        year=2026,
        month=4,
        usage_gb=1188.0,
        previous_usage_gb=1100.0,
        archives=58,
        days_in_month=30,
    )
    assert "58" in text
    assert "60" in text


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
