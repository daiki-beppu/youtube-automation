#!/usr/bin/env python3
"""Evaluate the resumable state of the music chain."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

EXIT_SKIP = 0
EXIT_ERROR = 1
EXIT_RUN = 10

_OUTPUT = Path("20-documentation/suno-prompts.json")


class ManifestError(ValueError):
    """Raised when the bundled chain manifest is inconsistent."""


def _manifest_path() -> Path:
    return Path(__file__).with_name("music-chain-manifest.json")


def _validate_manifest() -> None:
    manifest = json.loads(_manifest_path().read_text(encoding="utf-8"))
    if manifest.get("chainId") != "music":
        raise ManifestError("chainId must be music")
    steps = manifest.get("steps")
    if not isinstance(steps, list) or len(steps) != 1 or not isinstance(steps[0], dict):
        raise ManifestError("steps must contain prompt only")
    if (steps[0].get("id"), steps[0].get("skill")) != ("prompt", "music"):
        raise ManifestError("prompt step owner is inconsistent")


def evaluate(collection_path: Path, step: str) -> tuple[int, dict[str, object]]:
    if step != "prompt":
        raise ManifestError(f"unknown step: {step}")
    if not collection_path.is_dir():
        raise ManifestError(f"collection path is not a directory: {collection_path}")
    output = collection_path / _OUTPUT
    if not output.is_file() or output.stat().st_size == 0:
        return EXIT_RUN, {
            "step": "prompt",
            "decision": "run",
            "reason": "prompt_missing",
            "missing": [_OUTPUT.as_posix()],
        }
    return EXIT_SKIP, {
        "step": "prompt",
        "decision": "skip",
        "reason": "prompt_complete",
        "outputs": [_OUTPUT.as_posix()],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection-path", type=Path, required=True)
    parser.add_argument("--step", choices=("prompt",), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _validate_manifest()
        exit_code, result = evaluate(args.collection_path, args.step)
    except (OSError, json.JSONDecodeError, ManifestError) as exc:
        print(json.dumps({"step": args.step, "decision": "error", "reason": str(exc)}, ensure_ascii=False))
        return EXIT_ERROR
    print(json.dumps(result, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
