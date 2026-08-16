#!/usr/bin/env python3
"""Executable state, artifact, and untrusted-data contract for persona design."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from youtube_automation.core.errors import DocumentRenderError
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import read_published_json_document

PERSONA_FIELDS = (
    "vocabulary",
    "emotional_triggers",
    "viewing_scenes",
    "search_keywords",
    "avoid_appeals",
    "channel_implications",
)
_CANONICAL_ROUTES = {
    "persona": "channel-strategy --persona",
    "flop": "analytics --flop",
}
_SOURCE_ANNOTATION = re.compile(r"出典:\s*(?:推測|[A-Za-z0-9_.-]+\.(?:md|json))(?=[）)\]}、,;；\s]*$)")


class PersonaContractError(ValueError):
    """Raised when a persona flow would continue without trusted prerequisites."""


def flow_status(channel_dir: Path, *, allow_viewing_scene_skip: bool = False) -> dict[str, str]:
    viewer_voice = channel_dir / "docs" / "plans" / "viewer-voice-analysis.json"
    persona = channel_dir / "docs" / "channel" / "personas" / "persona-definition.md"
    viewing_scene = channel_dir / "docs" / "plans" / "viewing-scene-matrix.md"
    if not viewer_voice.is_file():
        return {"status": "blocked", "next": "channel-research --voice", "reason": "viewer_voice_missing"}
    document = read_published_json_document(viewer_voice, RepositorySchema.CHANNEL_RESEARCH_REPORT)
    if not isinstance(document, dict) or document.get("report_type") != "viewer_voice":
        raise PersonaContractError("viewer voice report_type must be viewer_voice")
    if not persona.is_file():
        return {"status": "ready", "next": "draft-persona", "reason": "viewer_voice_ready"}
    if not viewing_scene.is_file() and not allow_viewing_scene_skip:
        return {"status": "blocked", "next": "channel-strategy --scene", "reason": "viewing_scene_missing"}
    return {
        "status": "ready",
        "next": "finalize-persona",
        "reason": "viewing_scene_skipped" if not viewing_scene.is_file() else "viewing_scene_ready",
    }


def sanitize_persona_fields(payload: object) -> dict[str, list[str]]:
    """Accept only structured persona fields; never forward raw external instructions."""
    if not isinstance(payload, Mapping):
        raise PersonaContractError("persona payload must be an object")
    unknown = sorted(set(payload) - set(PERSONA_FIELDS))
    if unknown:
        raise PersonaContractError(f"untrusted or unknown persona fields: {', '.join(unknown)}")
    missing = [field for field in PERSONA_FIELDS if field not in payload]
    if missing:
        raise PersonaContractError(f"missing persona fields: {', '.join(missing)}")
    result: dict[str, list[str]] = {}
    for field in PERSONA_FIELDS:
        values = payload[field]
        if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
            raise PersonaContractError(f"{field} must be a list of non-empty strings")
        normalized = [value.strip() for value in values]
        if not all(_SOURCE_ANNOTATION.search(value) for value in normalized):
            raise PersonaContractError(f"{field} の各項目には出典: <入力ファイル名> または 出典: 推測が必要です")
        result[field] = normalized
    return result


def resolve_persona_artifact(channel_dir: Path) -> tuple[Path, str]:
    current = channel_dir / "docs" / "channel" / "personas" / "persona-definition.md"
    legacy = channel_dir / "docs" / "audience-persona.md"
    if current.is_file():
        return current, "current"
    if legacy.is_file():
        return legacy, "legacy-fallback"
    raise PersonaContractError("persona artifact is missing")


def route_skill(intent: str) -> str:
    if intent in {"audience-persona", "postmortem"}:
        raise PersonaContractError(f"legacy route is not executable: {intent}")
    try:
        return _CANONICAL_ROUTES[intent]
    except KeyError as exc:
        raise PersonaContractError(f"unknown route intent: {intent}") from exc


def flop_analysis_inputs(channel_dir: Path) -> list[str]:
    """Return read-only persona-chain evidence; never launch child skills."""
    relative_paths = (
        "docs/plans/viewer-voice-analysis.json",
        "docs/channel/personas/persona-definition.md",
        "docs/plans/viewing-scene-matrix.md",
    )
    inputs: list[str] = []
    for relative in relative_paths:
        path = channel_dir / relative
        if not path.is_file():
            continue
        if relative.endswith("viewer-voice-analysis.json"):
            document = read_published_json_document(path, RepositorySchema.CHANNEL_RESEARCH_REPORT)
            if not isinstance(document, dict) or document.get("report_type") != "viewer_voice":
                raise PersonaContractError("viewer voice report_type must be viewer_voice")
        inputs.append(relative)
    return inputs


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--channel-dir", type=Path, required=True)
    status.add_argument("--allow-viewing-scene-skip", action="store_true")
    resolve = sub.add_parser("resolve-persona")
    resolve.add_argument("--channel-dir", type=Path, required=True)
    route = sub.add_parser("route")
    route.add_argument("--intent", required=True)
    sanitize = sub.add_parser("sanitize")
    sanitize.add_argument("--input", type=Path, required=True)
    inputs = sub.add_parser("flop-inputs")
    inputs.add_argument("--channel-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "status":
            result: object = flow_status(
                args.channel_dir,
                allow_viewing_scene_skip=args.allow_viewing_scene_skip,
            )
        elif args.command == "resolve-persona":
            path, source = resolve_persona_artifact(args.channel_dir)
            result = {"path": str(path), "source": source}
        elif args.command == "route":
            result = {"skill": route_skill(args.intent)}
        elif args.command == "sanitize":
            result = sanitize_persona_fields(json.loads(args.input.read_text(encoding="utf-8")))
        else:
            result = {"inputs": flop_analysis_inputs(args.channel_dir)}
    except (DocumentRenderError, OSError, json.JSONDecodeError, PersonaContractError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
