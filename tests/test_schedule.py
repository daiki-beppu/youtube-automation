from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.schedule import get_schedule_timezone


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
