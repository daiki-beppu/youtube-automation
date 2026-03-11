"""
time_utils モジュールのユニットテスト

テスト対象: utils/time_utils.py
副作用のない純粋関数（時間フォーマット変換）を検証する。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.time_utils import (
    format_duration_display,
    format_duration_mmss,
    format_duration_mss,
    format_duration_short,
    format_timestamp,
)

# ---------------------------------------------------------------------------
# format_duration_mss: 秒 → m:ss
# ---------------------------------------------------------------------------

class TestFormatDurationMss:
    def test_zero(self):
        assert format_duration_mss(0) == "0:00"

    def test_under_one_minute(self):
        assert format_duration_mss(59) == "0:59"

    def test_exactly_one_minute(self):
        assert format_duration_mss(60) == "1:00"

    def test_just_under_one_hour(self):
        assert format_duration_mss(3599) == "59:59"

    def test_exactly_one_hour(self):
        assert format_duration_mss(3600) == "60:00"

    def test_float_truncated(self):
        assert format_duration_mss(225.7) == "3:45"

    def test_typical_value(self):
        assert format_duration_mss(225) == "3:45"

    def test_single_digit_seconds_padded(self):
        assert format_duration_mss(61) == "1:01"


# ---------------------------------------------------------------------------
# format_duration_mmss: 分(float) → mm:ss
# ---------------------------------------------------------------------------

class TestFormatDurationMmss:
    def test_zero(self):
        assert format_duration_mmss(0) == "00:00"

    def test_half_minute(self):
        assert format_duration_mmss(0.5) == "00:30"

    def test_one_minute(self):
        assert format_duration_mmss(1.0) == "01:00"

    def test_typical_value(self):
        assert format_duration_mmss(3.75) == "03:45"

    def test_large_value(self):
        assert format_duration_mmss(59.99) == "59:59"

    def test_over_one_hour(self):
        assert format_duration_mmss(120.5) == "120:30"


# ---------------------------------------------------------------------------
# format_timestamp: 秒 → H:MM:SS or MM:SS
# ---------------------------------------------------------------------------

class TestFormatTimestamp:
    def test_zero(self):
        assert format_timestamp(0) == "00:00"

    def test_just_over_one_minute(self):
        assert format_timestamp(65) == "01:05"

    def test_just_under_one_hour(self):
        assert format_timestamp(3599) == "59:59"

    def test_exactly_one_hour(self):
        assert format_timestamp(3600) == "1:00:00"

    def test_complex_value(self):
        # 7261 = 2h 1m 1s
        assert format_timestamp(7261) == "2:01:01"

    def test_minutes_padded_with_hours(self):
        assert format_timestamp(3660) == "1:01:00"


# ---------------------------------------------------------------------------
# format_duration_short: 秒 → 短縮表示 (5m, 1h, 2.5h)
# ---------------------------------------------------------------------------

class TestFormatDurationShort:
    def test_five_minutes(self):
        assert format_duration_short(300) == "5m"

    def test_rounding_to_nearest_5(self):
        # 2099s = 34.98min → rounds to 35m
        assert format_duration_short(2099) == "35m"

    def test_boundary_35_minutes_switches_to_hours(self):
        # 35min = 2100s → total_minutes >= 35 → hours mode
        # 35/60 = 0.583h → round(0.583*2)/2 = round(1.166)/2 = 1/2 = 0.5h
        assert format_duration_short(2100) == "0.5h"

    def test_one_hour(self):
        # 4500s = 75min → 1.25h → round(2.5)/2 = round(2.5)/2 = 2/2 = 1h (banker's rounding: 2)
        # Actually round(2.5) = 2 in Python (banker's rounding)
        assert format_duration_short(4500) == "1h"

    def test_one_and_half_hours(self):
        # 6300s = 105min → 1.75h → round(3.5)/2 = 4/2 = 2h (banker's rounding: round(3.5)=4)
        assert format_duration_short(6300) == "2h"

    def test_two_hours(self):
        assert format_duration_short(7200) == "2h"

    def test_three_hours(self):
        assert format_duration_short(10800) == "3h"

    def test_very_small_rounds_to_5m(self):
        # 60s = 1min → round(1/5)*5 = 0 → max(0,5) = 5
        assert format_duration_short(60) == "5m"

    def test_half_hour(self):
        # 1800s = 30min → round(30/5)*5 = 30
        assert format_duration_short(1800) == "30m"


# ---------------------------------------------------------------------------
# format_duration_display: 秒 → 人間可読表示
# ---------------------------------------------------------------------------

class TestFormatDurationDisplay:
    def test_under_35min_rounds_to_5(self):
        # 300s = 5min
        assert format_duration_display(300) == "5 min"

    def test_under_35min_typical(self):
        # 1500s = 25min
        assert format_duration_display(1500) == "25 min"

    def test_under_35min_small_rounds_up(self):
        # 60s = 1min → round(1/5)*5 = 0 → max(0,5) = 5
        assert format_duration_display(60) == "5 min"

    def test_35_to_75_min_is_one_hour(self):
        # 2100s = 35min
        assert format_duration_display(2100) == "1 Hour"
        # 4499s = 74.98min
        assert format_duration_display(4499) == "1 Hour"

    def test_75_to_105_min_is_1_5_hours(self):
        # 4500s = 75min
        assert format_duration_display(4500) == "1.5 Hours"
        # 6299s = 104.98min
        assert format_duration_display(6299) == "1.5 Hours"

    def test_105_to_135_min_is_2_hours(self):
        # 6300s = 105min
        assert format_duration_display(6300) == "2 Hours"
        # 8099s = 134.98min
        assert format_duration_display(8099) == "2 Hours"

    def test_above_135_min_rounds_to_half_hours(self):
        # 8100s = 135min = 2.25h → round(4.5)/2 = 4/2 = 2h (banker's rounding)
        # Actually round(4.5) = 4 in Python
        assert format_duration_display(8100) == "2 Hours"

    def test_three_hours(self):
        # 10800s = 180min = 3h
        assert format_duration_display(10800) == "3 Hours"

    def test_2_5_hours(self):
        # 9000s = 150min = 2.5h → round(5.0)/2 = 5/2 = 2.5
        assert format_duration_display(9000) == "2.5 Hours"
