"""YouTube adapter boundary for domain modules."""

from youtube_automation.core.youtube_tags import normalize_youtube_tags, parse_youtube_tags, youtube_tag_chars
from youtube_automation.domains.uploads.quota import (
    DAILY_BUCKET_LIMITS,
    UNIT_COSTS,
    UNIT_POOL_LIMIT,
    complete_collection_quota_plan,
    quota_shortages,
)

__all__ = [
    "DAILY_BUCKET_LIMITS",
    "UNIT_COSTS",
    "UNIT_POOL_LIMIT",
    "complete_collection_quota_plan",
    "normalize_youtube_tags",
    "parse_youtube_tags",
    "quota_shortages",
    "youtube_tag_chars",
]
