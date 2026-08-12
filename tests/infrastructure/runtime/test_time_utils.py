"""time_utils のユニットテスト（Khorikov 出力ベース）

純粋関数のみ。mock なし。parametrize でケースをまとめ、
テスト名はビジネス上の振る舞いを記述する。
"""

import pytest

from youtube_automation.infrastructure.runtime.time_utils import (
    format_duration_display,
    format_duration_mmss,
    format_duration_mss,
    format_duration_short,
    format_localized_duration_display,
    format_timestamp,
)

# ---------------------------------------------------------------------------
# format_duration_mss: タイムスタンプ表示用の m:ss フォーマット
# ---------------------------------------------------------------------------


class TestFormatDurationMss:
    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (0, "0:00"),
            (59, "0:59"),
            (60, "1:00"),
            (61, "1:01"),
            (225, "3:45"),
            (3599, "59:59"),
            (3600, "60:00"),
        ],
    )
    def test_formats_seconds_as_m_ss(self, seconds, expected):
        assert format_duration_mss(seconds) == expected

    def test_truncates_fractional_seconds(self):
        assert format_duration_mss(225.7) == "3:45"


# ---------------------------------------------------------------------------
# format_duration_mmss: 分(float)を mm:ss に変換
# ---------------------------------------------------------------------------


class TestFormatDurationMmss:
    @pytest.mark.parametrize(
        "minutes, expected",
        [
            (0, "00:00"),
            (0.5, "00:30"),
            (1.0, "01:00"),
            (3.75, "03:45"),
            (59.99, "59:59"),
            (120.5, "120:30"),
        ],
    )
    def test_formats_minutes_as_mm_ss(self, minutes, expected):
        assert format_duration_mmss(minutes) == expected


# ---------------------------------------------------------------------------
# format_timestamp: YouTube チャプター用タイムスタンプ
# ---------------------------------------------------------------------------


class TestFormatTimestamp:
    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (0, "00:00"),
            (65, "01:05"),
            (3599, "59:59"),
        ],
    )
    def test_formats_as_mm_ss_under_one_hour(self, seconds, expected):
        assert format_timestamp(seconds) == expected

    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (3600, "1:00:00"),
            (3660, "1:01:00"),
            (7261, "2:01:01"),
        ],
    )
    def test_formats_as_h_mm_ss_over_one_hour(self, seconds, expected):
        assert format_timestamp(seconds) == expected


# ---------------------------------------------------------------------------
# format_duration_short: 短縮デュレーション (5m, 1h, 2.5h)
# ---------------------------------------------------------------------------


class TestFormatDurationShort:
    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (60, "5m"),  # 1分 → 最低5分に丸め
            (300, "5m"),  # 5分
            (1800, "30m"),  # 30分
            (2099, "35m"),  # 34.98分 → 35分に丸め
        ],
    )
    def test_rounds_to_5_minute_increments(self, seconds, expected):
        assert format_duration_short(seconds) == expected

    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (2100, "0.5h"),  # 35分 → 時間表示に切替
            (4500, "1h"),  # 75分 → banker's rounding
            (6300, "2h"),  # 105分
            (7200, "2h"),  # 120分
            (10800, "3h"),  # 180分
        ],
    )
    def test_rounds_to_half_hour_increments(self, seconds, expected):
        assert format_duration_short(seconds) == expected


# ---------------------------------------------------------------------------
# format_duration_display: 人間可読なデュレーション表示
# ---------------------------------------------------------------------------


class TestFormatDurationDisplay:
    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (60, "5 min"),  # 1分 → 最低5分
            (300, "5 min"),  # 5分
            (1500, "25 min"),  # 25分
        ],
    )
    def test_shows_minutes_under_35min(self, seconds, expected):
        assert format_duration_display(seconds) == expected

    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (2100, "1 Hour"),  # 35分 → 1 Hour
            (4499, "1 Hour"),  # 74.98分 → 1 Hour
            (4500, "1.5 Hours"),  # 75分 → 1.5 Hours
            (6299, "1.5 Hours"),  # 104.98分 → 1.5 Hours
            (6300, "2 Hours"),  # 105分 → 2 Hours
            (8099, "2 Hours"),  # 134.98分 → 2 Hours
        ],
    )
    def test_shows_fixed_hour_labels(self, seconds, expected):
        assert format_duration_display(seconds) == expected

    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (8100, "2 Hours"),  # 135分 → banker's rounding
            (9000, "2.5 Hours"),  # 150分
            (10800, "3 Hours"),  # 180分
        ],
    )
    def test_rounds_to_half_hours_above_135min(self, seconds, expected):
        assert format_duration_display(seconds) == expected


class TestFormatLocalizedDurationDisplay:
    @pytest.mark.parametrize(
        ("locale", "expected"),
        [
            ("ja", "1.5時間"),
            ("en", "1.5 Hours"),
            ("de", "1.5 Std"),
            ("fr", "1.5 heures"),
            ("ES-es", "1.5 horas"),
            ("it_IT", "1.5 ore"),
            ("fil-PH", "1.5 oras"),
        ],
    )
    def test_formats_supported_base_locale_after_case_and_region_normalization(self, locale, expected):
        assert format_localized_duration_display(90 * 60, locale) == expected

    def test_unknown_valid_locale_uses_observable_english_fallback(self, caplog):
        with caplog.at_level("WARNING"):
            result = format_localized_duration_display(3600, "pt-BR")

        assert result == "1 Hour"
        assert "pt-BR" in caplog.text
        assert "English" in caplog.text

    @pytest.mark.parametrize(
        "locale",
        [
            "en-a-aaa-b-bbb",
            "en-x-private",
            "x-private",
            "i-default",
        ],
    )
    def test_accepts_structurally_valid_bcp47_tags(self, locale):
        assert format_localized_duration_display(3600, locale) == "1 Hour"

    @pytest.mark.parametrize(
        "locale",
        [
            "en-12",
            "de-419-DE",
            "en-US-Latn",
            "en-a-aaa-a-bbb",
            "en-1901-1901",
        ],
    )
    def test_rejects_structurally_invalid_bcp47_tags(self, locale):
        with pytest.raises(ValueError, match="locale"):
            format_localized_duration_display(3600, locale)

    @pytest.mark.parametrize(
        ("locale", "expected_bytes"),
        [
            ("ja", "1時間".encode()),
            ("en", b"1 Hour"),
            ("de", b"1 Std"),
        ],
    )
    def test_preserves_existing_54_minute_output_bytes(self, locale, expected_bytes):
        assert format_localized_duration_display(54 * 60, locale).encode() == expected_bytes

    @pytest.mark.parametrize("locale", ["", "   ", None, 42])
    def test_invalid_locale_fails_loudly(self, locale):
        with pytest.raises((TypeError, ValueError), match="locale"):
            format_localized_duration_display(3600, locale)
