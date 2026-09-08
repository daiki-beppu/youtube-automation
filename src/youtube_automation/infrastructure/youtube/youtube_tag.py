"""Compatibility exports for shared YouTube tag representation rules."""

from youtube_automation.core.youtube_tags import (
    normalize_youtube_tags,
    parse_youtube_tags,
    youtube_tag_chars,
)

__all__ = ["normalize_youtube_tags", "parse_youtube_tags", "youtube_tag_chars"]
