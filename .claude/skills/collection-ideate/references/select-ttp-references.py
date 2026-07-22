"""Select collection-ideate TTP references from config and collection history."""

from __future__ import annotations

import sys
from pathlib import Path

from youtube_automation.configuration import channel_dir
from youtube_automation.utils.skill_config import load_skill_config
from youtube_automation.utils.thumbnail_references import (
    plan_ttp_reference_assignments,
    resolve_dedup_recent_collections,
)


def main() -> None:
    references = [Path(line.strip()) for line in sys.stdin if line.strip()]
    candidate_count = int(sys.argv[1])
    thumbnail_config = load_skill_config("thumbnail").get("image_generation", {}).get("gemini", {})
    reference_config = thumbnail_config.get("reference_images", {}) if isinstance(thumbnail_config, dict) else {}
    root = channel_dir()
    selected = plan_ttp_reference_assignments(
        references,
        candidate_count,
        True,
        benchmark_root=root / "data" / "thumbnail_compare" / "benchmark",
        channel_dir=root,
        dedup_recent_collections=resolve_dedup_recent_collections(reference_config.get("dedup_recent_collections")),
    )
    for reference in selected:
        print(reference)


if __name__ == "__main__":
    main()
