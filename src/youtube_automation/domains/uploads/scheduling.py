"""Timezone-aware upload timestamps and channel default publication scheduling."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from youtube_automation.core.errors import ValidationError


class _ScheduleTimezone(Protocol):
    """Timezone information required by timestamp helpers."""

    @property
    def timezone(self) -> ZoneInfo: ...


def get_schedule_timezone(schedule_config: _ScheduleTimezone) -> ZoneInfo:
    """Resolve the configured schedule timezone."""
    return schedule_config.timezone


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


def now_in_schedule_tz(schedule_config: _ScheduleTimezone) -> datetime:
    """schedule.timezone の現在時刻を TZ-aware datetime として返す.

    永続化用 timestamp の生成を一点に集約し、`datetime.now()`（TZ-naive）の混入を防ぐ。
    返り値は ensure_tz_aware で自己診断してから返す。
    """
    tz = get_schedule_timezone(schedule_config)
    return ensure_tz_aware(datetime.now(tz), context="now_in_schedule_tz")


def parse_default_publish_time(value: str) -> time:
    """`HH:MM` / `HH:MM:SS` を `datetime.time` に変換する."""
    parts = str(value).strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"default_publish_time は HH:MM または HH:MM:SS で指定してください: {value!r}")
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    return time(hour=hour, minute=minute, second=second)


def resolve_default_publish_at(config, *, now: datetime | None = None) -> str | None:
    """チャンネル既定の予約投稿時刻から、次回の ISO 8601 publishAt を返す."""
    api = config.youtube.api
    default_time = getattr(api, "default_publish_time", None)
    if not default_time:
        return None

    tz_name = getattr(api, "default_publish_timezone", "Asia/Tokyo") or "Asia/Tokyo"
    tz = ZoneInfo(tz_name)
    publish_time = parse_default_publish_time(default_time)

    current = now or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    else:
        current = current.astimezone(tz)

    candidate = current.replace(
        hour=publish_time.hour,
        minute=publish_time.minute,
        second=publish_time.second,
        microsecond=0,
    )
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate.isoformat()
