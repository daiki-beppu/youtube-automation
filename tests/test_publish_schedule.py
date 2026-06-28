"""Channel default publish schedule helpers."""

from __future__ import annotations

from datetime import datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from youtube_automation.utils.publish_schedule import parse_default_publish_time, resolve_default_publish_at


def _config(default_publish_time: str | None = "20:00", timezone: str = "Asia/Tokyo") -> SimpleNamespace:
    return SimpleNamespace(
        youtube=SimpleNamespace(
            api=SimpleNamespace(
                default_publish_time=default_publish_time,
                default_publish_timezone=timezone,
            )
        )
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("20:30", time(hour=20, minute=30)),
        ("20:30:15", time(hour=20, minute=30, second=15)),
    ],
)
def test_parse_default_publish_time_accepts_hh_mm_and_hh_mm_ss(value: str, expected: time) -> None:
    assert parse_default_publish_time(value) == expected


@pytest.mark.parametrize("value", ["20", "20:30:15:10"])
def test_parse_default_publish_time_rejects_invalid_field_count(value: str) -> None:
    with pytest.raises(ValueError, match="HH:MM"):
        parse_default_publish_time(value)


@pytest.mark.parametrize("value", ["20:xx", "25:00", "20:61"])
def test_parse_default_publish_time_rejects_invalid_numeric_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_default_publish_time(value)


def test_resolve_default_publish_at_uses_configured_timezone() -> None:
    now = datetime(2099, 1, 1, 19, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    assert resolve_default_publish_at(_config("20:00", "Asia/Tokyo"), now=now) == "2099-01-01T20:00:00+09:00"


def test_resolve_default_publish_at_rejects_unknown_timezone() -> None:
    with pytest.raises(ZoneInfoNotFoundError):
        resolve_default_publish_at(_config("20:00", "Invalid/Timezone"))


def test_resolve_default_publish_at_returns_none_when_not_configured() -> None:
    assert resolve_default_publish_at(_config(None)) is None
