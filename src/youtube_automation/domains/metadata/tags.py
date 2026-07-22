"""Tag assembly helpers."""

from __future__ import annotations

from typing import Iterable

from youtube_automation.utils.youtube_tag import normalize_youtube_tags


def build_collection_tags(tags: Iterable[str]) -> list[str]:
    return normalize_youtube_tags(list(tags)[:50])


def build_short_tags(base_tags: Iterable[str], theme_tags: Iterable[str]) -> list[str]:
    """Build Shorts tags while preserving source order and the 50-tag limit."""
    return normalize_youtube_tags(["Shorts", *base_tags, *theme_tags][:50])
