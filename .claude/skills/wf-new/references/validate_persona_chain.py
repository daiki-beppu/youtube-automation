#!/usr/bin/env python3
"""Validate the canonical persona and viewing-scene document chain."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from youtube_automation.core.errors import AutomationError
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import read_published_json_document


def validate_persona_chain(persona_json: Path, scene_json: Path) -> None:
    """Validate both published pairs and their bidirectional references."""
    persona = read_published_json_document(persona_json, RepositorySchema.CHANNEL_STRATEGY)
    scene = read_published_json_document(scene_json, RepositorySchema.CHANNEL_STRATEGY)
    persona_id = persona["persona"]["id"]
    scene_ids = {item["id"] for item in scene["scenes"]}
    if scene["persona_id"] != persona_id or not set(persona["scene_ids"]).issubset(scene_ids):
        raise ValueError("persona/scene の参照が一致しません")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persona-json", type=Path, required=True)
    parser.add_argument("--scene-json", type=Path, required=True)
    args = parser.parse_args()
    try:
        validate_persona_chain(args.persona_json, args.scene_json)
    except (AutomationError, KeyError, TypeError, ValueError) as exc:
        print(f"persona chain 検証失敗: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
