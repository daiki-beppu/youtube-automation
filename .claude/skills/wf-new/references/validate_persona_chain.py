#!/usr/bin/env python3
"""Validate the canonical persona and viewing-scene document chain."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from youtube_automation.application.documents import (
    validate_channel_strategy_document_type,
    validate_persona_scene_references,
)
from youtube_automation.core.errors import AutomationError
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import read_published_json_document


def validate_persona_document(persona_json: Path) -> dict[str, object]:
    """Validate a published persona pair in the producer's intermediate state."""
    persona = read_published_json_document(persona_json, RepositorySchema.CHANNEL_STRATEGY)
    return validate_channel_strategy_document_type(persona, "persona")


def validate_persona_chain(persona_json: Path, scene_json: Path) -> None:
    """Validate both published pairs and their bidirectional references."""
    persona = read_published_json_document(persona_json, RepositorySchema.CHANNEL_STRATEGY)
    scene = read_published_json_document(scene_json, RepositorySchema.CHANNEL_STRATEGY)
    validate_persona_scene_references(persona, scene, require_nonempty=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persona-json", type=Path, required=True)
    parser.add_argument("--scene-json", type=Path)
    args = parser.parse_args()
    try:
        if args.scene_json is None:
            validate_persona_document(args.persona_json)
        else:
            validate_persona_chain(args.persona_json, args.scene_json)
    except AutomationError as exc:
        print(f"persona chain 検証失敗: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
