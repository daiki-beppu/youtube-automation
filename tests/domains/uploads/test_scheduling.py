from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from youtube_automation.configuration import ScheduleConfig
from youtube_automation.core.errors import ValidationError
from youtube_automation.domains.uploads.scheduling import (
    ensure_tz_aware,
    get_schedule_timezone,
    now_in_schedule_tz,
    parse_default_publish_time,
    resolve_default_publish_at,
)


def test_get_schedule_timezone_uses_configured_timezone():
    tz = get_schedule_timezone(ScheduleConfig(timezone=ZoneInfo("America/New_York")))

    assert tz.key == "America/New_York"
    assert datetime(2026, 1, 1, tzinfo=tz).utcoffset() == timedelta(hours=-5)


def test_get_schedule_timezone_defaults_to_tokyo_when_schedule_is_missing():
    tz = get_schedule_timezone(ScheduleConfig())

    assert datetime(2026, 1, 1, tzinfo=tz).utcoffset() == timedelta(hours=9)


def test_ensure_tz_aware_returns_aware_datetime_unchanged():
    dt = datetime(2026, 1, 1, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    assert ensure_tz_aware(dt, context="test") is dt


def test_ensure_tz_aware_accepts_utc():
    dt = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)

    assert ensure_tz_aware(dt, context="test") is dt


def test_ensure_tz_aware_raises_on_naive_datetime():
    naive = datetime(2026, 1, 1, 10, 0)

    with pytest.raises(ValidationError, match="TZ-naive"):
        ensure_tz_aware(naive, context="workflow-state.json::uploaded_at")


def test_ensure_tz_aware_includes_context_in_message():
    naive = datetime(2026, 1, 1, 10, 0)

    with pytest.raises(ValidationError, match="upload_tracking.json::upload_time"):
        ensure_tz_aware(naive, context="upload_tracking.json::upload_time")


def test_now_in_schedule_tz_defaults_to_tokyo():
    now = now_in_schedule_tz(ScheduleConfig())

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(hours=9)


def _config(default_time: str, timezone_name: str = "Asia/Tokyo") -> SimpleNamespace:
    api = SimpleNamespace(
        default_publish_time=default_time,
        default_publish_timezone=timezone_name,
    )
    return SimpleNamespace(youtube=SimpleNamespace(api=api))


def test_parse_default_publish_time_preserves_seconds() -> None:
    assert parse_default_publish_time("23:59:58") == time(23, 59, 58)


@pytest.mark.parametrize("value", ["24:00", "23:60", "23:59:60", "12", "12:00:00:00"])
def test_parse_default_publish_time_rejects_invalid_values(value: str) -> None:
    with pytest.raises((ValueError, OverflowError)):
        parse_default_publish_time(value)


def test_resolve_default_publish_at_uses_seconds_at_day_boundary() -> None:
    result = resolve_default_publish_at(
        _config("00:00:01", "UTC"),
        now=datetime(2026, 7, 23, 0, 0, 1, tzinfo=timezone.utc),
    )

    assert result == "2026-07-24T00:00:01+00:00"
