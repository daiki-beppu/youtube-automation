#!/usr/bin/env python3
"""Evaluate the resumable state of the channel-strategy chain."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from youtube_automation.core.errors import DocumentRenderError
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import read_published_json_document

EXIT_SKIP = 0
EXIT_ERROR = 1
EXIT_RUN = 10
EXIT_BLOCKED = 20

_VIEWER_VOICE = "docs/plans/viewer-voice-analysis.json"
_PERSONA = "docs/channel/personas/persona-definition.json"
_SCENE = "docs/plans/viewing-scene-matrix.json"
_CONSTRAINTS = "docs/channel/creative-constraints.json"


class ManifestError(ValueError):
    """Raised when the bundled chain manifest is inconsistent."""


def _manifest_path() -> Path:
    return Path(__file__).with_name("channel-strategy-chain-manifest.json")


def _validate_manifest() -> None:
    manifest = json.loads(_manifest_path().read_text(encoding="utf-8"))
    if manifest.get("chainId") != "channel-strategy":
        raise ManifestError("chainId must be channel-strategy")
    steps = manifest.get("steps")
    if not isinstance(steps, list) or len(steps) != 3 or not all(isinstance(step, dict) for step in steps):
        raise ManifestError("steps must contain persona, scene, and constraints")
    identities = [(step.get("id"), step.get("skill")) for step in steps]
    if identities != [
        ("persona", "channel-strategy"),
        ("scene", "channel-strategy"),
        ("constraints", "channel-strategy"),
    ]:
        raise ManifestError("step order or owner is inconsistent")


def _artifact_exists(channel_dir: Path, relative: str) -> bool:
    path = channel_dir / relative
    if not path.is_file() or not path.with_suffix(".html").is_file():
        return False
    schema = (
        RepositorySchema.CHANNEL_RESEARCH_REPORT if relative == _VIEWER_VOICE else RepositorySchema.CHANNEL_STRATEGY
    )
    document = read_published_json_document(path, schema)
    return isinstance(document, dict)


def _evaluate_persona(channel_dir: Path) -> tuple[int, dict[str, object]]:
    if not _artifact_exists(channel_dir, _VIEWER_VOICE):
        return EXIT_BLOCKED, {
            "step": "persona",
            "decision": "blocked",
            "reason": "viewer_voice_missing",
            "missing": [_VIEWER_VOICE],
            "next": "channel-research --voice",
        }
    viewer_voice = read_published_json_document(
        channel_dir / _VIEWER_VOICE,
        RepositorySchema.CHANNEL_RESEARCH_REPORT,
    )
    if not isinstance(viewer_voice, dict) or viewer_voice.get("report_type") != "viewer_voice":
        raise ManifestError("viewer voice report_type must be viewer_voice")
    if not _artifact_exists(channel_dir, _PERSONA):
        return EXIT_RUN, {
            "step": "persona",
            "decision": "run",
            "reason": "persona_missing",
            "missing": [_PERSONA],
        }
    return EXIT_SKIP, {
        "step": "persona",
        "decision": "skip",
        "reason": "persona_complete",
        "outputs": [_PERSONA],
    }


def _evaluate_scene(channel_dir: Path) -> tuple[int, dict[str, object]]:
    if not _artifact_exists(channel_dir, _PERSONA):
        return EXIT_BLOCKED, {
            "step": "scene",
            "decision": "blocked",
            "reason": "persona_missing",
            "missing": [_PERSONA],
            "next": "channel-strategy --persona",
        }
    if not _artifact_exists(channel_dir, _SCENE):
        return EXIT_RUN, {
            "step": "scene",
            "decision": "run",
            "reason": "scene_missing",
            "missing": [_SCENE],
        }
    return EXIT_SKIP, {
        "step": "scene",
        "decision": "skip",
        "reason": "scene_complete",
        "outputs": [_SCENE],
    }


def _evaluate_constraints(channel_dir: Path) -> tuple[int, dict[str, object]]:
    prerequisites = (_PERSONA, _SCENE)
    missing = [relative for relative in prerequisites if not _artifact_exists(channel_dir, relative)]
    if missing:
        return EXIT_BLOCKED, {
            "step": "constraints",
            "decision": "blocked",
            "reason": "constraints_prerequisites_missing",
            "missing": missing,
            "next": "channel-strategy --persona" if _PERSONA in missing else "channel-strategy --scene",
        }
    if not _artifact_exists(channel_dir, _CONSTRAINTS):
        return EXIT_RUN, {
            "step": "constraints",
            "decision": "run",
            "reason": "constraints_missing",
            "missing": [_CONSTRAINTS],
        }
    return EXIT_SKIP, {
        "step": "constraints",
        "decision": "skip",
        "reason": "constraints_complete",
        "outputs": [_CONSTRAINTS],
    }


def evaluate(channel_dir: Path, step: str) -> tuple[int, dict[str, object]]:
    if step == "persona":
        return _evaluate_persona(channel_dir)
    if step == "scene":
        return _evaluate_scene(channel_dir)
    if step == "constraints":
        return _evaluate_constraints(channel_dir)
    raise ManifestError(f"unknown step: {step}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-dir", type=Path, required=True)
    parser.add_argument("--step", choices=("persona", "scene", "constraints"), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _validate_manifest()
        exit_code, result = evaluate(args.channel_dir, args.step)
    except (DocumentRenderError, OSError, json.JSONDecodeError, ManifestError) as exc:
        print(json.dumps({"step": args.step, "decision": "error", "reason": str(exc)}, ensure_ascii=False))
        return EXIT_ERROR
    print(json.dumps(result, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
