"""Schedule-related helpers shared by upload agents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from youtube_automation.utils.exceptions import ConfigError

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
