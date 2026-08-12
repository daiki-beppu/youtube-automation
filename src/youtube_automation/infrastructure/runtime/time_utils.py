"""時間・デュレーションのフォーマットユーティリティ。

Usage:
    from youtube_automation.infrastructure.runtime.time_utils import (
        format_duration_mss,
        format_duration_mmss,
        format_timestamp,
    )
"""

import logging

logger = logging.getLogger(__name__)

_GRANDFATHERED_LANGUAGE_TAGS = frozenset(
    {
        "art-lojban",
        "cel-gaulish",
        "en-gb-oed",
        "i-ami",
        "i-bnn",
        "i-default",
        "i-enochian",
        "i-hak",
        "i-klingon",
        "i-lux",
        "i-mingo",
        "i-navajo",
        "i-pwn",
        "i-tao",
        "i-tay",
        "i-tsu",
        "no-bok",
        "no-nyn",
        "sgn-be-fr",
        "sgn-be-nl",
        "sgn-ch-de",
        "zh-guoyu",
        "zh-hakka",
        "zh-min",
        "zh-min-nan",
        "zh-xiang",
    }
)


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
    """共通の丸め数値を locale の単位で表示し、未知の有効 locale は英語 fallback を警告する."""
    if not isinstance(locale, str):
        raise TypeError(f"locale は文字列でなければなりません: {type(locale).__name__}")
    normalized_locale = locale.strip().replace("_", "-")
    if not _is_well_formed_bcp47_tag(normalized_locale):
        raise ValueError(f"locale の形式が不正です: {locale!r}")

    base_locale = normalized_locale.casefold().split("-", 1)[0]
    value, unit = _rounded_duration(total_seconds)
    units = {
        "en": {"minute": "min", "hour": "Hour" if value == "1" else "Hours"},
        "de": {"minute": "Min", "hour": "Std"},
        "ja": {"minute": "分", "hour": "時間"},
        "fr": {"minute": "min", "hour": "heure" if value == "1" else "heures"},
        "es": {"minute": "min", "hour": "hora" if value == "1" else "horas"},
        "it": {"minute": "min", "hour": "ora" if value == "1" else "ore"},
        "fil": {"minute": "min", "hour": "oras"},
    }
    locale_units = units.get(base_locale)
    if locale_units is None:
        # YouTube が追加した有効 locale で metadata 全体を止めず、英語使用を warning で可視化する。
        logger.warning("duration_display locale %r has no dedicated units; using English units", locale)
        locale_units = units["en"]
    separator = "" if base_locale == "ja" else " "
    return f"{value}{separator}{locale_units[unit]}"


def _is_well_formed_bcp47_tag(locale: str) -> bool:
    """RFC 5646 の Language-Tag ABNF と重複禁止規則を構造検証する."""
    if not locale or not locale.isascii():
        return False
    subtags = locale.casefold().split("-")
    if any(not _is_alphanumeric(subtag, minimum=1, maximum=8) for subtag in subtags):
        return False
    if locale.casefold() in _GRANDFATHERED_LANGUAGE_TAGS:
        return True
    if subtags[0] == "x":
        return len(subtags) > 1

    language = subtags[0]
    if not _is_alpha(language, minimum=2, maximum=8):
        return False
    if len(language) == 4 or len(language) > 4:
        index = 1
    else:
        index = 1
        extlang_count = 0
        while index < len(subtags) and extlang_count < 3 and _is_alpha(subtags[index], minimum=3, maximum=3):
            index += 1
            extlang_count += 1

    if index < len(subtags) and _is_alpha(subtags[index], minimum=4, maximum=4):
        index += 1
    if index < len(subtags) and (
        _is_alpha(subtags[index], minimum=2, maximum=2) or (len(subtags[index]) == 3 and subtags[index].isdigit())
    ):
        index += 1

    variants: set[str] = set()
    while index < len(subtags) and _is_variant(subtags[index]):
        if subtags[index] in variants:
            return False
        variants.add(subtags[index])
        index += 1

    extension_singletons: set[str] = set()
    while index < len(subtags) and _is_extension_singleton(subtags[index]):
        singleton = subtags[index]
        if singleton in extension_singletons:
            return False
        extension_singletons.add(singleton)
        index += 1
        extension_start = index
        while index < len(subtags) and _is_alphanumeric(subtags[index], minimum=2, maximum=8):
            index += 1
        if index == extension_start:
            return False

    if index < len(subtags) and subtags[index] == "x":
        index += 1
        private_use_start = index
        while index < len(subtags) and _is_alphanumeric(subtags[index], minimum=1, maximum=8):
            index += 1
        if index == private_use_start:
            return False

    return index == len(subtags)


def _is_alpha(value: str, *, minimum: int, maximum: int) -> bool:
    return minimum <= len(value) <= maximum and value.isascii() and value.isalpha()


def _is_alphanumeric(value: str, *, minimum: int, maximum: int) -> bool:
    return minimum <= len(value) <= maximum and value.isascii() and value.isalnum()


def _is_variant(value: str) -> bool:
    return _is_alphanumeric(value, minimum=5, maximum=8) or (
        len(value) == 4 and value[0].isdigit() and _is_alphanumeric(value, minimum=4, maximum=4)
    )


def _is_extension_singleton(value: str) -> bool:
    return len(value) == 1 and value != "x" and value.isascii() and value.isalnum()


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
