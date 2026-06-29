"""Suno collection artifact path and route contracts shared by scripts and utils."""

from __future__ import annotations

DOCUMENTATION_DIRNAME = "20-documentation"
SUNO_PATTERNS_FILENAME = "suno-patterns.yaml"
SUNO_LYRICS_MD_FILENAME = "suno-lyrics.md"
SUNO_LYRICS_JSON_FILENAME = "suno-lyrics.json"
SUNO_PROMPTS_MD_FILENAME = "suno-prompts.md"
SUNO_PROMPTS_JSON_FILENAME = "suno-prompts.json"

SUNO_PROMPTS_ROUTE = "/suno/prompts.json"
COLLECTIONS_ROUTE = "/collections"
DOWNLOADED_ROUTE_SUFFIX = "/downloaded"
SUNO_PLAYLISTS_ROUTE = "/suno/playlists"


def collection_downloaded_route(collection_id: str) -> str:
    """個別 collection の download 完了通知 POST ルートを組み立てる。"""
    return f"{COLLECTIONS_ROUTE}/{collection_id}{DOWNLOADED_ROUTE_SUFFIX}"
