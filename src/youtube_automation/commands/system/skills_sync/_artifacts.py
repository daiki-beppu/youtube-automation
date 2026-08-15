"""Report artifact writers declared by distributed skills."""

from __future__ import annotations

import argparse

from youtube_automation.domains.skills.inventory import SkillInventory


def cmd_artifacts(args: argparse.Namespace) -> int:
    """List artifact writers and summarize duplicate ownership."""
    from youtube_automation.commands.system.skills_sync import _asset_root

    inventory = SkillInventory(_asset_root("skills"))
    writers: dict[str, list[str]] = {}
    for skill_dir in inventory.skill_directories():
        for artifact in inventory.artifacts(skill_dir.name).writes:
            writers.setdefault(artifact, []).append(skill_dir.name)

    rows = [
        (artifact, ", ".join(sorted(names)))
        for artifact, names in sorted(writers.items())
        if not args.duplicates_only or len(names) >= 2
    ]
    if rows:
        width = max(len("成果物"), *(len(artifact) for artifact, _names in rows))
        print(f"{'成果物':<{width}}  writer")
        for artifact, names in rows:
            print(f"{artifact:<{width}}  {names}")

    duplicate_count = sum(len(names) >= 2 for names in writers.values())
    print(f"\n重複 writer: {duplicate_count} 件 / 宣言された成果物: {len(writers)} 件")
    return 0
