"""Schedule-related helpers shared by upload agents."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from youtube_automation.utils.exceptions import ConfigError, ValidationError

SCHEDULE_SECTION = "schedule"
TIMEZONE_KEY = "timezone"
DEFAULT_SCHEDULE_TIMEZONE = "Asia/Tokyo"


def get_schedule_timezone(schedule_config: Mapping[str, Any]) -> ZoneInfo:
    """Resolve the configured schedule timezone."""
    schedule = schedule_config.get(SCHEDULE_SECTION, {})
    if not isinstance(schedule, Mapping):
        raise ConfigError("schedule_config.json の schedule は object である必要があります")

    timezone_name = schedule.get(TIMEZONE_KEY, DEFAULT_SCHEDULE_TIMEZONE)
    if not isinstance(timezone_name, str) or not timezone_name:
        raise ConfigError("schedule_config.json の schedule.timezone は空でない文字列である必要があります")

    return ZoneInfo(timezone_name)


def ensure_tz_aware(dt: datetime, *, context: str) -> datetime:
    """永続化対象の datetime が TZ-aware であることを保証する防御ヘルパ.

    workflow-state.json / upload_tracking.json などへ書き込む timestamp が
    TZ-naive のまま混入する再リグレッション（#359 関連）を *書き込み時点で* 検出する。
    読み手側 backfill（TZ-naive を schedule TZ で補完）で吸収されると見過ごされるため、
    書き手側でも自己診断する。

    Args:
        dt: 検証対象の datetime
        context: 例外メッセージに含める発生箇所（例: "workflow-state.json::uploaded_at"）

    Returns:
        dt（TZ-aware であればそのまま）

    Raises:
        ValidationError: dt.tzinfo が None（TZ-naive）の場合
    """
    if dt.tzinfo is None:
        raise ValidationError(
            f"TZ-naive datetime を永続化しようとしました ({context}): {dt!r}. "
            "datetime.now(tz) / now_in_schedule_tz() など TZ-aware な値を使ってください"
        )
    return dt


def now_in_schedule_tz(schedule_config: Mapping[str, Any]) -> datetime:
    """schedule.timezone の現在時刻を TZ-aware datetime として返す.

    永続化用 timestamp の生成を一点に集約し、`datetime.now()`（TZ-naive）の混入を防ぐ。
    返り値は ensure_tz_aware で自己診断してから返す。
    """
    tz = get_schedule_timezone(schedule_config)
    return ensure_tz_aware(datetime.now(tz), context="now_in_schedule_tz")
