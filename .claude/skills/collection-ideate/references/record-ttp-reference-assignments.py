"""Persist collection-ideate TTP assignments for future rotation decisions."""

from __future__ import annotations

import sys
from pathlib import Path

from youtube_automation.utils.config import channel_dir
from youtube_automation.utils.thumbnail_references import record_ttp_reference_assignments


def _resolve_from_channel(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def main() -> None:
    root = channel_dir()
    collection_dir = _resolve_from_channel(root, sys.argv[1])
    selected_reference = _resolve_from_channel(root, sys.argv[2])
    record_ttp_reference_assignments(
        collection_dir / "20-documentation" / "thumbnail-prompts.md",
        [selected_reference],
        root,
    )


if __name__ == "__main__":
    main()
