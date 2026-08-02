"""Channel default publish time helpers."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


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
