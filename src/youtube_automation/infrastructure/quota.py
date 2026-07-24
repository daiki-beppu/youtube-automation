"""Infrastructure adapters for recording external API quota consumption."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from youtube_automation.infrastructure.cost_tracker import log_quota

_YOUTUBE_DATA_API_SERVICE = "youtube-data-api"


def youtube_quota_recorder(
    bucket: str,
    units: float,
    *,
    metadata: dict | None = None,
) -> Callable[[], None]:
    """Return an infrastructure callback for one YouTube API attempt."""
    return partial(
        log_quota,
        _YOUTUBE_DATA_API_SERVICE,
        bucket,
        units,
        metadata=metadata,
    )
