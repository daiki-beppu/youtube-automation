from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from youtube_automation.utils.exceptions import ConfigError, ValidationError
from youtube_automation.utils.schedule import (
    ensure_tz_aware,
    get_schedule_timezone,
    now_in_schedule_tz,
)


def test_get_schedule_timezone_uses_configured_timezone():
    tz = get_schedule_timezone({"schedule": {"timezone": "America/New_York"}})

    assert tz.key == "America/New_York"
    assert datetime(2026, 1, 1, tzinfo=tz).utcoffset() == timedelta(hours=-5)


def test_get_schedule_timezone_defaults_to_tokyo_when_schedule_is_missing():
    tz = get_schedule_timezone({})

    assert datetime(2026, 1, 1, tzinfo=tz).utcoffset() == timedelta(hours=9)


def test_get_schedule_timezone_rejects_non_mapping_schedule():
    with pytest.raises(ConfigError, match="schedule"):
        get_schedule_timezone({"schedule": "Asia/Tokyo"})


def test_get_schedule_timezone_rejects_empty_timezone():
    with pytest.raises(ConfigError, match="schedule.timezone"):
        get_schedule_timezone({"schedule": {"timezone": ""}})


# ─── ensure_tz_aware（書き込み側 TZ-naive 検出の防御コード, #533） ───


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


# ─── now_in_schedule_tz（永続化用 timestamp 生成の集約, #533） ───


def test_now_in_schedule_tz_returns_tz_aware_datetime():
    now = now_in_schedule_tz({"schedule": {"timezone": "Asia/Tokyo"}})

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(hours=9)


def test_now_in_schedule_tz_defaults_to_tokyo():
    now = now_in_schedule_tz({})

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(hours=9)


def test_now_in_schedule_tz_rejects_invalid_schedule_config():
    with pytest.raises(ConfigError, match="schedule"):
        now_in_schedule_tz({"schedule": "Asia/Tokyo"})
