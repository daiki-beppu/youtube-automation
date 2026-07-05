"""Shared `suno-lyrics.json` loading and shape validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.suno_artifact_contracts import SUNO_LYRICS_JSON_FILENAME


@dataclass(frozen=True)
class SunoLyricsEntry:
    """Validated external lyrics entry keyed by the final Suno prompt name."""

    name: str
    lyrics: str


def load_suno_lyrics_entries(lyrics_path: Path) -> list[SunoLyricsEntry]:
    """Load and validate `suno-lyrics.json` as ordered entries.

    `OSError` is intentionally allowed to propagate so CLI callers can preserve
    their own file-read error UX. JSON and shape errors become `ConfigError`.
    """
    try:
        raw = json.loads(lyrics_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{SUNO_LYRICS_JSON_FILENAME} is invalid JSON: {lyrics_path}") from exc
    return validate_suno_lyrics_entries(raw)


def validate_suno_lyrics_entries(raw: object) -> list[SunoLyricsEntry]:
    """Validate the public `suno-lyrics.json` shape shared by `/suno` and checks."""
    if not isinstance(raw, list):
        raise ConfigError(f"{SUNO_LYRICS_JSON_FILENAME} root must be a list")

    entries: list[SunoLyricsEntry] = []
    duplicates: set[str] = set()
    seen_names: set[str] = set()
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ConfigError(f"{SUNO_LYRICS_JSON_FILENAME}: entry {i} must be an object")
        name = item.get("name")
        lyrics = item.get("lyrics")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{SUNO_LYRICS_JSON_FILENAME}: entry {i}.name must be a non-empty string")
        if not isinstance(lyrics, str):
            raise ConfigError(f"{SUNO_LYRICS_JSON_FILENAME}: entry {i}.lyrics must be a string")
        clean_name = name.strip()
        if clean_name in seen_names:
            duplicates.add(clean_name)
        seen_names.add(clean_name)
        entries.append(SunoLyricsEntry(name=clean_name, lyrics=lyrics.rstrip()))

    if duplicates:
        duplicate_names = ", ".join(sorted(duplicates))
        raise ConfigError(f"{SUNO_LYRICS_JSON_FILENAME}: duplicated lyrics entry names: {duplicate_names}")

    return entries


def load_suno_lyrics_by_name(lyrics_path: Path) -> dict[str, str]:
    """Load `suno-lyrics.json` as `entry name -> lyrics`."""
    return {entry.name: entry.lyrics for entry in load_suno_lyrics_entries(lyrics_path)}
