"""Filesystem queries for DistroKid collection artifacts."""

from __future__ import annotations

from pathlib import Path


def find_distrokid_discs(collection_dir: Path) -> list[str]:
    """Return disc directories containing at least one MP3."""
    distrokid_dir = collection_dir / "30-distrokid"
    if not distrokid_dir.is_dir():
        return []
    return [
        directory.name
        for directory in sorted(distrokid_dir.iterdir())
        if directory.is_dir() and any(directory.glob("*.mp3"))
    ]
