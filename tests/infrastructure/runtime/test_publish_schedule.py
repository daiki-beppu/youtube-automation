from datetime import datetime, time, timezone
from types import SimpleNamespace

import pytest

from youtube_automation.infrastructure.runtime.publish_schedule import (
    parse_default_publish_time,
    resolve_default_publish_at,
)


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
