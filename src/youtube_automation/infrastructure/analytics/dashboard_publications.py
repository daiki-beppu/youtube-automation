"""dashboard の公開動画日時をローカル暦日別に集計する。"""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 1
ROLLING_WINDOW_DAYS = 365
CACHE_MAX_AGE = timedelta(hours=24)


def _parse_timestamp(value: str, *, field_name: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError(f"{field_name} は timezone-aware ISO 8601 でなければなりません")
    return timestamp.astimezone(UTC)


def _validate_payload(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    schema_version = value.get("schema_version")
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        return None

    fetched_at = value.get("fetched_at")
    timezone = value.get("timezone")
    days = value.get("days")
    if not isinstance(fetched_at, str) or not isinstance(timezone, str) or not isinstance(days, dict):
        return None

    try:
        _parse_timestamp(fetched_at, field_name="fetched_at")
        ZoneInfo(timezone)
        for local_day, count in days.items():
            if not isinstance(local_day, str) or type(count) is not int or count < 0:
                return None
            date.fromisoformat(local_day)
    except (ValueError, KeyError):
        return None
    return cast(dict[str, object], value)


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
        published_at = _parse_timestamp(value, field_name="published_at")
        if cutoff <= published_at <= fetched_at_utc:
            local_day = published_at.astimezone(local_timezone).date().isoformat()
            counts[local_day] += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "fetched_at": fetched_at_utc.isoformat(),
        "timezone": timezone,
        "days": dict(sorted(counts.items())),
    }


def load_fresh_dashboard_publications(source: Path, *, now: datetime) -> dict[str, object] | None:
    """有効かつ取得から24時間以内の公開履歴 cache を返す。"""
    if now.tzinfo is None:
        raise ValueError("now は timezone-aware datetime でなければなりません")

    try:
        value: object = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    payload = _validate_payload(value)
    if payload is None:
        return None

    fetched_at = _parse_timestamp(cast(str, payload["fetched_at"]), field_name="fetched_at")
    age = now.astimezone(UTC) - fetched_at
    if age < timedelta(0) or age > CACHE_MAX_AGE:
        return None
    return payload


def save_dashboard_publications(destination: Path, payload: dict[str, object]) -> None:
    """同一ディレクトリの一時ファイルを置換して payload を原子的に保存する。"""
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
