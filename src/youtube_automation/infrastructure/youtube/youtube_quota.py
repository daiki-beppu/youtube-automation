"""Compatibility exports for upload quota planning and shortage decisions."""

from youtube_automation.domains.uploads.quota import (
    DAILY_BUCKET_LIMITS,
    UNIT_COSTS,
    UNIT_POOL_LIMIT,
    UploadQuotaPlan,
    complete_collection_quota_plan,
    quota_shortages,
)

__all__ = [
    "DAILY_BUCKET_LIMITS",
    "UNIT_COSTS",
    "UNIT_POOL_LIMIT",
    "UploadQuotaPlan",
    "complete_collection_quota_plan",
    "quota_shortages",
]
