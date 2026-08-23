#!/usr/bin/env python3
"""Validate the canonical persona and viewing-scene document chain."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from youtube_automation.core.errors import AutomationError, DocumentValidationError
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import read_published_json_document


def validate_persona_chain(persona_json: Path, scene_json: Path) -> None:
    """Validate both published pairs and their bidirectional references."""
    persona = read_published_json_document(persona_json, RepositorySchema.CHANNEL_STRATEGY)
    scene = read_published_json_document(scene_json, RepositorySchema.CHANNEL_STRATEGY)
    if not isinstance(persona, dict) or not isinstance(scene, dict):
        raise DocumentValidationError("persona/scene は JSON object である必要があります")

    persona_value = persona.get("persona")
    scenes_value = scene.get("scenes")
    if not isinstance(persona_value, dict) or not isinstance(scenes_value, list):
        raise DocumentValidationError("persona/scene の参照構造が不正です")

    persona_id = persona_value.get("id")
    persona_scene_ids = persona.get("scene_ids")
    scene_ids = {item.get("id") for item in scenes_value if isinstance(item, dict)}
    if not isinstance(persona_scene_ids, list) or not persona_scene_ids or not scene_ids:
        raise DocumentValidationError("persona/scene の参照は空にできません")
    if scene.get("persona_id") != persona_id or set(persona_scene_ids) != scene_ids:
        raise DocumentValidationError("persona/scene の参照が双方向に一致しません")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persona-json", type=Path, required=True)
    parser.add_argument("--scene-json", type=Path, required=True)
    args = parser.parse_args()
    try:
        validate_persona_chain(args.persona_json, args.scene_json)
    except AutomationError as exc:
        print(f"persona chain 検証失敗: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
