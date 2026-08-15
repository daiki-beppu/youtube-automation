#!/usr/bin/env python3
"""Evaluate the resumable state of the channel-strategy chain."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

EXIT_SKIP = 0
EXIT_ERROR = 1
EXIT_RUN = 10
EXIT_BLOCKED = 20

_VIEWER_VOICE = "docs/plans/viewer-voice-analysis.md"
_PERSONA = "docs/channel/personas/persona-definition.md"


class ManifestError(ValueError):
    """Raised when the bundled chain manifest is inconsistent."""


def _manifest_path() -> Path:
    return Path(__file__).with_name("channel-strategy-chain-manifest.json")


def _validate_manifest() -> None:
    manifest = json.loads(_manifest_path().read_text(encoding="utf-8"))
    if manifest.get("chainId") != "channel-strategy":
        raise ManifestError("chainId must be channel-strategy")
    steps = manifest.get("steps")
    if not isinstance(steps, list) or len(steps) != 1 or not isinstance(steps[0], dict):
        raise ManifestError("steps must contain only the persona step")
    step = steps[0]
    if step.get("id") != "persona" or step.get("skill") != "channel-strategy":
        raise ManifestError("persona step owner is inconsistent")


def _artifact_exists(channel_dir: Path, relative: str) -> bool:
    path = channel_dir / relative
    return path.is_file() and path.stat().st_size > 0


def evaluate(channel_dir: Path) -> tuple[int, dict[str, object]]:
    if not _artifact_exists(channel_dir, _VIEWER_VOICE):
        return EXIT_BLOCKED, {
            "step": "persona",
            "decision": "blocked",
            "reason": "viewer_voice_missing",
            "missing": [_VIEWER_VOICE],
            "next": "channel-research --voice",
        }
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-dir", type=Path, required=True)
    parser.add_argument("--step", choices=("persona",), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _validate_manifest()
        exit_code, result = evaluate(args.channel_dir)
    except (OSError, json.JSONDecodeError, ManifestError) as exc:
        print(json.dumps({"step": args.step, "decision": "error", "reason": str(exc)}, ensure_ascii=False))
        return EXIT_ERROR
    print(json.dumps(result, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
