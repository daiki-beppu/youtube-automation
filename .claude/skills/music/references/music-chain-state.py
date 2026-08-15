#!/usr/bin/env python3
"""Evaluate the resumable state of the music chain."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import yaml

from youtube_automation.configuration.skills import load_skill_config
from youtube_automation.core.errors import ConfigError
from youtube_automation.domains.suno.config import infer_suno_mode

EXIT_SKIP = 0
EXIT_ERROR = 1
EXIT_RUN = 10
EXIT_BLOCKED = 20

_PROMPT_OUTPUTS = (
    Path("20-documentation/suno-patterns.yaml"),
    Path("20-documentation/suno-prompts.md"),
    Path("20-documentation/suno-prompts.json"),
)
_LYRIC_OUTPUTS = (
    Path("20-documentation/suno-lyrics.md"),
    Path("20-documentation/suno-lyrics.json"),
)


class ManifestError(ValueError):
    """Raised when the bundled chain manifest is inconsistent."""


def _manifest_path() -> Path:
    return Path(__file__).with_name("music-chain-manifest.json")


def _validate_manifest() -> None:
    manifest = json.loads(_manifest_path().read_text(encoding="utf-8"))
    if manifest.get("chainId") != "music":
        raise ManifestError("chainId must be music")
    steps = manifest.get("steps")
    if not isinstance(steps, list) or len(steps) != 2 or not all(isinstance(step, dict) for step in steps):
        raise ManifestError("steps must contain prompt and lyric")
    identities = [(step.get("id"), step.get("skill")) for step in steps]
    if identities != [("prompt", "music"), ("lyric", "music")]:
        raise ManifestError("step order or owner is inconsistent")


def _artifact_exists(collection_path: Path, relative: Path) -> bool:
    path = collection_path / relative
    return path.is_file() and path.stat().st_size > 0


def _channel_dir(collection_path: Path) -> Path:
    for candidate in (collection_path, *collection_path.parents):
        if (candidate / "config" / "channel" / "youtube.json").is_file():
            return candidate
    raise ManifestError(f"channel config not found for collection: {collection_path}")


def _load_mapping(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ManifestError(f"mapping required: {path}")
    return loaded


def _evaluate_prompt(collection_path: Path) -> tuple[int, dict[str, object]]:
    output = _PROMPT_OUTPUTS[-1]
    if not _artifact_exists(collection_path, output):
        return EXIT_RUN, {
            "step": "prompt",
            "decision": "run",
            "reason": "prompt_missing",
            "missing": [output.as_posix()],
        }
    return EXIT_SKIP, {
        "step": "prompt",
        "decision": "skip",
        "reason": "prompt_complete",
        "outputs": [output.as_posix()],
    }


def _evaluate_lyric(collection_path: Path) -> tuple[int, dict[str, object]]:
    missing_prerequisites = [
        relative.as_posix() for relative in _PROMPT_OUTPUTS if not _artifact_exists(collection_path, relative)
    ]
    if missing_prerequisites:
        return EXIT_BLOCKED, {
            "step": "lyric",
            "decision": "blocked",
            "reason": "prompt_prerequisites_missing",
            "missing": missing_prerequisites,
            "next": "music --prompt",
        }

    channel_dir = _channel_dir(collection_path)
    youtube_config = _load_mapping(channel_dir / "config" / "channel" / "youtube.json")
    if youtube_config.get("music_engine") != "suno":
        return EXIT_BLOCKED, {
            "step": "lyric",
            "decision": "blocked",
            "reason": "music_engine_not_suno",
        }

    patterns_path = collection_path / _PROMPT_OUTPUTS[0]
    patterns = _load_mapping(patterns_path)
    prompt_config = load_skill_config("music.prompt", use_cache=False, channel_dir=channel_dir)
    genre_line = prompt_config.get("genre_line")
    if not isinstance(genre_line, str):
        raise ManifestError("music.prompt.genre_line must be a string")
    if patterns.get("mode") != "vocal" and infer_suno_mode(genre_line) != "vocal":
        return EXIT_BLOCKED, {
            "step": "lyric",
            "decision": "blocked",
            "reason": "lyrics_not_required",
        }

    missing = [relative.as_posix() for relative in _LYRIC_OUTPUTS if not _artifact_exists(collection_path, relative)]
    if missing:
        return EXIT_RUN, {
            "step": "lyric",
            "decision": "run",
            "reason": "lyric_missing",
            "missing": missing,
        }
    return EXIT_SKIP, {
        "step": "lyric",
        "decision": "skip",
        "reason": "lyric_complete",
        "outputs": [relative.as_posix() for relative in _LYRIC_OUTPUTS],
    }


def evaluate(collection_path: Path, step: str) -> tuple[int, dict[str, object]]:
    if not collection_path.is_dir():
        raise ManifestError(f"collection path is not a directory: {collection_path}")
    if step == "prompt":
        return _evaluate_prompt(collection_path)
    if step == "lyric":
        return _evaluate_lyric(collection_path)
    raise ManifestError(f"unknown step: {step}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection-path", type=Path, required=True)
    parser.add_argument("--step", choices=("prompt", "lyric"), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _validate_manifest()
        exit_code, result = evaluate(args.collection_path, args.step)
    except (OSError, json.JSONDecodeError, yaml.YAMLError, ConfigError, ManifestError) as exc:
        print(json.dumps({"step": args.step, "decision": "error", "reason": str(exc)}, ensure_ascii=False))
        return EXIT_ERROR
    print(json.dumps(result, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
