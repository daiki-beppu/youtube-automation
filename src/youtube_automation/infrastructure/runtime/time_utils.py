"""時間・デュレーションのフォーマットユーティリティ。

Usage:
    from youtube_automation.infrastructure.runtime.time_utils import (
        format_duration_mss,
        format_duration_mmss,
        format_timestamp,
    )
"""


def format_duration_mss(seconds: float) -> str:
    """秒数を m:ss 形式にフォーマット（例: 225.0 → '3:45'）。"""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def format_duration_mmss(minutes: float) -> str:
    """分を mm:ss 形式に変換（例: 3.75 → '03:45'）。"""
    m = int(minutes)
    s = int((minutes - m) * 60)
    return f"{m:02d}:{s:02d}"


def format_timestamp(seconds: int) -> str:
    """秒数を YouTube チャプター形式のタイムスタンプに変換。

    Returns:
        str: H:MM:SS（1時間以上）または MM:SS
    """
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_duration_short(total_seconds: int | float) -> str:
    """秒数を短縮デュレーション表示に変換（例: '1h', '2.5h', '25m'）。"""
    total_minutes = total_seconds / 60
    if total_minutes < 35:
        rounded = round(total_minutes / 5) * 5
        return f"{max(rounded, 5)}m"
    total_hours = total_minutes / 60
    rounded_half = round(total_hours * 2) / 2
    if rounded_half == int(rounded_half):
        return f"{int(rounded_half)}h"
    return f"{rounded_half}h"


def format_duration_display(total_seconds: int | float) -> str:
    """秒数を人間可読なデュレーション表示に丸める。

    ルール:
    - < 35分 → 5分単位（例: "25 min"）
    - 35-75分 → "1 Hour"
    - 75-105分 → "1.5 Hours"
    - 105-135分 → "2 Hours"
    - 以降 0.5時間単位
    """
    value, unit = _rounded_duration(total_seconds)
    if unit == "minute":
        return f"{value} min"
    return f"{value} Hour" if value == "1" else f"{value} Hours"


def format_localized_duration_display(total_seconds: int | float, locale: str) -> str:
    """共通の丸め数値を locale ごとの単位で表示する."""
    value, unit = _rounded_duration(total_seconds)
    units = {
        "en": {"minute": "min", "hour": "Hour" if value == "1" else "Hours"},
        "de": {"minute": "Min", "hour": "Std"},
        "ja": {"minute": "分", "hour": "時間"},
    }
    locale_units = units.get(locale)
    if locale_units is None:
        raise ValueError(f"duration_display に対応していない locale: {locale!r}。対応 locale は ja, en, de です")
    separator = "" if locale == "ja" else " "
    return f"{value}{separator}{locale_units[unit]}"


def _rounded_duration(total_seconds: int | float) -> tuple[str, str]:
    """既存の尺丸め規則を表示用の数値と単位種別へ正規化する."""
    total_minutes = total_seconds / 60
    if total_minutes < 35:
        rounded_minutes = max(round(total_minutes / 5) * 5, 5)
        return str(rounded_minutes), "minute"
    if total_minutes < 75:
        return "1", "hour"
    if total_minutes < 105:
        return "1.5", "hour"
    if total_minutes < 135:
        return "2", "hour"

    rounded_hours = round(total_minutes / 30) / 2
    if rounded_hours == int(rounded_hours):
        return str(int(rounded_hours)), "hour"
    return str(rounded_hours), "hour"
