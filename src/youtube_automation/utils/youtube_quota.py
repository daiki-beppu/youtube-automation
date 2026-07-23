"""YouTube Data API の現行日次 bucket / unit pool 契約。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DAILY_BUCKET_LIMITS = {
    "videos.insert": 100,
    "search.list": 100,
}
UNIT_POOL_LIMIT = 10_000
UNIT_COSTS = {
    "videos.insert": 1,
    "search.list": 1,
    "videos.list": 1,
    "thumbnails.set": 50,
    "playlistItems.insert": 50,
}
_RESET_TIMEZONE = ZoneInfo("America/Los_Angeles")


@dataclass(frozen=True)
class UploadQuotaPlan:
    """Complete Collection 1件の保守的な API call 見積もり。"""

    bucket_calls: dict[str, int]
    unit_pool_calls: dict[str, int]

    @property
    def unit_pool_units(self) -> int:
        return sum(UNIT_COSTS[method] * count for method, count in self.unit_pool_calls.items())


def complete_collection_quota_plan(*, playlist_inserts: int = 1) -> UploadQuotaPlan:
    """upload + schedule lookup + dedup + thumbnail + playlist の見積もりを返す。"""
    if playlist_inserts < 0:
        raise ValueError("playlist_inserts must be >= 0")
    unit_pool_calls = {
        "videos.list": 2,
        "thumbnails.set": 1,
    }
    if playlist_inserts:
        unit_pool_calls["playlistItems.insert"] = playlist_inserts
    return UploadQuotaPlan(
        bucket_calls={"videos.insert": 1, "search.list": 2},
        unit_pool_calls=unit_pool_calls,
    )


def quota_shortages(
    plan: UploadQuotaPlan,
    entries: list[dict],
    *,
    now: datetime | None = None,
) -> list[str]:
    """ローカル記録済みの当日使用量に plan を加え、既知の不足を返す。"""
    current = now or datetime.now(timezone.utc)
    current_reset_date = current.astimezone(_RESET_TIMEZONE).date()
    today = [
        entry
        for entry in entries
        if _entry_reset_date(entry.get("timestamp")) == current_reset_date
        and entry.get("service") == "youtube-data-api"
    ]

    shortages: list[str] = []
    for bucket, planned in plan.bucket_calls.items():
        used = sum(1 for entry in today if entry.get("bucket") == bucket)
        limit = DAILY_BUCKET_LIMITS[bucket]
        if used + planned > limit:
            shortages.append(f"{bucket}: used {used} + planned {planned} > daily {limit} calls")

    unit_used = sum(float(entry.get("units", 0)) for entry in today if entry.get("bucket") not in DAILY_BUCKET_LIMITS)
    if unit_used + plan.unit_pool_units > UNIT_POOL_LIMIT:
        shortages.append(f"unit pool: used {int(unit_used)} + planned {plan.unit_pool_units} > daily {UNIT_POOL_LIMIT}")
    return shortages


def _entry_reset_date(value: object):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_RESET_TIMEZONE).date()
