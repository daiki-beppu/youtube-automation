"""dashboard の公開動画日時をローカル暦日別に集計する。"""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TypedDict, cast
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 1
ROLLING_WINDOW_DAYS = 365
CACHE_MAX_AGE = timedelta(hours=24)


class DashboardPublicationError(TypedDict):
    code: str
    message: str
    attempted_at: str


class DashboardPublicationsRequired(TypedDict):
    schema_version: int
    fetched_at: str
    timezone: str
    days: dict[str, int]


class DashboardPublications(DashboardPublicationsRequired, total=False):
    error: DashboardPublicationError


def _parse_timestamp(value: str, *, field_name: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError(f"{field_name} は timezone-aware ISO 8601 でなければなりません")
    return timestamp.astimezone(UTC)


def _validate_payload(value: object) -> DashboardPublications | None:
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
    error = value.get("error")
    error_attempted_at: str | None = None
    if "error" in value:
        if not isinstance(error, dict):
            return None
        if not isinstance(error.get("code"), str) or not isinstance(error.get("message"), str):
            return None
        attempted_at_value = error.get("attempted_at")
        if not isinstance(attempted_at_value, str):
            return None
        error_attempted_at = attempted_at_value

    try:
        _parse_timestamp(fetched_at, field_name="fetched_at")
        if error_attempted_at is not None:
            _parse_timestamp(error_attempted_at, field_name="error.attempted_at")
        ZoneInfo(timezone)
        for local_day, count in days.items():
            if not isinstance(local_day, str) or type(count) is not int or count < 0:
                return None
            date.fromisoformat(local_day)
    except (ValueError, KeyError):
        return None
    return cast(DashboardPublications, value)


def build_dashboard_publications(
    published_at_values: Iterable[str],
    *,
    timezone: str,
    fetched_at: datetime,
) -> DashboardPublications:
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

    return DashboardPublications(
        schema_version=SCHEMA_VERSION,
        fetched_at=fetched_at_utc.isoformat(),
        timezone=timezone,
        days=dict(sorted(counts.items())),
    )


def load_dashboard_publications(source: Path) -> DashboardPublications | None:
    """鮮度に関係なく有効な公開履歴 cache を返す。"""
    try:
        value: object = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return _validate_payload(value)


def load_fresh_dashboard_publications(source: Path, *, now: datetime) -> DashboardPublications | None:
    """有効かつ取得から24時間以内の公開履歴 cache を返す。"""
    if now.tzinfo is None:
        raise ValueError("now は timezone-aware datetime でなければなりません")

    payload = load_dashboard_publications(source)
    if payload is None:
        return None

    fetched_at = _parse_timestamp(payload["fetched_at"], field_name="fetched_at")
    age = now.astimezone(UTC) - fetched_at
    if age < timedelta(0) or age > CACHE_MAX_AGE:
        return None
    return payload


def with_dashboard_publication_error(
    payload: Mapping[str, object],
    *,
    code: str,
    message: str,
    attempted_at: datetime,
) -> DashboardPublications:
    """公開履歴の前回値を維持して構造化された更新失敗を付与する。"""
    validated = _validate_payload(payload)
    if validated is None:
        raise ValueError("有効な公開履歴 payload が必要です")
    if attempted_at.tzinfo is None:
        raise ValueError("attempted_at は timezone-aware datetime でなければなりません")

    result = validated.copy()
    result["error"] = DashboardPublicationError(
        code=code,
        message=message,
        attempted_at=attempted_at.astimezone(UTC).isoformat(),
    )
    return result


def save_dashboard_publications(destination: Path, payload: Mapping[str, object]) -> None:
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
