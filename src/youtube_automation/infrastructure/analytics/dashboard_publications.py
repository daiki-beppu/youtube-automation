"""dashboard の公開動画日時をローカル暦日別に集計する。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 1
ROLLING_WINDOW_DAYS = 365


def _parse_published_at(value: str) -> datetime:
    published_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if published_at.tzinfo is None:
        raise ValueError("published_at は timezone-aware ISO 8601 でなければなりません")
    return published_at.astimezone(UTC)


def build_dashboard_publications(
    published_at_values: Iterable[str],
    *,
    timezone: str,
    fetched_at: datetime,
) -> dict[str, object]:
    """公開日時を rolling 365 日のローカル暦日別件数へ変換する。"""
    if fetched_at.tzinfo is None:
        raise ValueError("fetched_at は timezone-aware datetime でなければなりません")

    fetched_at_utc = fetched_at.astimezone(UTC)
    cutoff = fetched_at_utc - timedelta(days=ROLLING_WINDOW_DAYS)
    local_timezone = ZoneInfo(timezone)
    counts: Counter[str] = Counter()

    for value in published_at_values:
        published_at = _parse_published_at(value)
        if cutoff <= published_at <= fetched_at_utc:
            local_day = published_at.astimezone(local_timezone).date().isoformat()
            counts[local_day] += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "fetched_at": fetched_at_utc.isoformat(),
        "timezone": timezone,
        "days": dict(sorted(counts.items())),
    }
