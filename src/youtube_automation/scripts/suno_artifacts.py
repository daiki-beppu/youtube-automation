"""Backward-compatible imports for Suno artifact contracts.

The contract values live in ``youtube_automation.utils.suno_artifact_contracts`` so
utils code does not depend on the scripts layer.
"""

from __future__ import annotations

from youtube_automation.utils.suno_artifact_contracts import (
    COLLECTIONS_ROUTE,
    DOCUMENTATION_DIRNAME,
    DOWNLOADED_ROUTE_SUFFIX,
    SUNO_LYRICS_JSON_FILENAME,
    SUNO_LYRICS_MD_FILENAME,
    SUNO_PATTERNS_FILENAME,
    SUNO_PLAYLISTS_ROUTE,
    SUNO_PROMPTS_JSON_FILENAME,
    SUNO_PROMPTS_MD_FILENAME,
    SUNO_PROMPTS_ROUTE,
    collection_downloaded_route,
)

__all__ = [
    "COLLECTIONS_ROUTE",
    "DOCUMENTATION_DIRNAME",
    "DOWNLOADED_ROUTE_SUFFIX",
    "SUNO_LYRICS_JSON_FILENAME",
    "SUNO_LYRICS_MD_FILENAME",
    "SUNO_PATTERNS_FILENAME",
    "SUNO_PLAYLISTS_ROUTE",
    "SUNO_PROMPTS_JSON_FILENAME",
    "SUNO_PROMPTS_MD_FILENAME",
    "SUNO_PROMPTS_ROUTE",
    "collection_downloaded_route",
]
