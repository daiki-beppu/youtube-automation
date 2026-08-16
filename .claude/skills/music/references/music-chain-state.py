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
from youtube_automation.domains.suno.downloaded.archive import count_audio_files
from youtube_automation.domains.suno.prompts import read_suno_prompt_entries

EXIT_SKIP = 0
EXIT_ERROR = 1
EXIT_RUN = 10
EXIT_BLOCKED = 20

_PROMPT_OUTPUTS = (
    Path("20-documentation/suno-patterns.yaml"),
    Path("20-documentation/suno-prompts.html"),
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
    if not isinstance(steps, list) or len(steps) != 4 or not all(isinstance(step, dict) for step in steps):
        raise ManifestError("steps must contain prompt, lyric, generate, and master")
    identities = [(step.get("id"), step.get("skill")) for step in steps]
    if identities != [
        ("prompt", "music"),
        ("lyric", "music"),
        ("generate", "music"),
        ("master", "music"),
    ]:
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
    if youtube_config.get("music_engine") not in {"suno", "minimax"}:
        return EXIT_BLOCKED, {
            "step": "lyric",
            "decision": "blocked",
            "reason": "music_engine_not_lyric_capable",
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


def _music_engine(collection_path: Path) -> str:
    channel_dir = _channel_dir(collection_path)
    youtube_config = _load_mapping(channel_dir / "config" / "channel" / "youtube.json")
    engine = youtube_config.get("music_engine")
    if engine not in {"suno", "lyria", "minimax"}:
        raise ManifestError("config/channel/youtube.json::music_engine must be suno, lyria, or minimax")
    return engine


def _workflow_state(collection_path: Path) -> dict[str, object]:
    state_path = collection_path / "workflow-state.json"
    if not state_path.is_file():
        return {}
    try:
        loaded = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"invalid workflow-state.json: {state_path}") from exc
    if not isinstance(loaded, dict):
        raise ManifestError(f"mapping required: {state_path}")
    return loaded


def _evaluate_suno_generate(collection_path: Path) -> tuple[int, dict[str, object]]:
    missing_prerequisites = [
        relative.as_posix() for relative in _PROMPT_OUTPUTS if not _artifact_exists(collection_path, relative)
    ]
    if missing_prerequisites:
        return EXIT_BLOCKED, {
            "step": "generate",
            "engine": "suno",
            "decision": "blocked",
            "reason": "prompt_prerequisites_missing",
            "missing": missing_prerequisites,
            "next": "music --prompt",
        }

    try:
        entry_count = len(read_suno_prompt_entries(collection_path))
    except ValueError as exc:
        raise ManifestError(str(exc)) from exc
    if entry_count < 1:
        raise ManifestError("suno-prompts.json must contain at least one entry")
    expected_count = entry_count * 2
    actual_count = count_audio_files(collection_path / "02-Individual-music")
    state = _workflow_state(collection_path)
    planning = state.get("planning")
    music = planning.get("music") if isinstance(planning, dict) else None
    assets = state.get("assets")
    strict_complete = (
        isinstance(music, dict)
        and isinstance(music.get("suno_playlist_url"), str)
        and bool(music["suno_playlist_url"])
        and music.get("expected_file_count") == expected_count
        and music.get("actual_file_count") == actual_count
        and music.get("missing_file_count") == 0
        and actual_count >= expected_count
        and isinstance(assets, dict)
        and assets.get("music_downloaded") is True
    )
    if not strict_complete:
        return EXIT_RUN, {
            "step": "generate",
            "engine": "suno",
            "decision": "run",
            "reason": "suno_strict_completion_missing",
            "expected_file_count": expected_count,
            "actual_file_count": actual_count,
        }
    return EXIT_SKIP, {
        "step": "generate",
        "engine": "suno",
        "decision": "skip",
        "reason": "suno_generate_complete",
        "outputs": ["02-Individual-music/"],
    }


def _evaluate_generate(collection_path: Path) -> tuple[int, dict[str, object]]:
    engine = _music_engine(collection_path)
    if engine == "suno":
        return _evaluate_suno_generate(collection_path)
    output = Path("01-master/master.mp3")
    if not _artifact_exists(collection_path, output):
        return EXIT_RUN, {
            "step": "generate",
            "engine": engine,
            "decision": "run",
            "reason": f"{engine}_master_missing",
            "missing": [output.as_posix()],
        }
    return EXIT_SKIP, {
        "step": "generate",
        "engine": engine,
        "decision": "skip",
        "reason": f"{engine}_generate_complete",
        "outputs": [output.as_posix()],
    }


def _evaluate_master(collection_path: Path) -> tuple[int, dict[str, object]]:
    engine = _music_engine(collection_path)
    if engine in {"lyria", "minimax"}:
        return EXIT_SKIP, {
            "step": "master",
            "engine": engine,
            "decision": "skip",
            "reason": f"{engine}_master_not_required",
        }

    output = Path("01-master/master.mp3")
    if _artifact_exists(collection_path, output):
        return EXIT_SKIP, {
            "step": "master",
            "engine": "suno",
            "decision": "skip",
            "reason": "master_complete",
            "outputs": [output.as_posix()],
        }

    generate_exit, generate_state = _evaluate_suno_generate(collection_path)
    if generate_exit != EXIT_SKIP:
        return EXIT_BLOCKED, {
            "step": "master",
            "engine": "suno",
            "decision": "blocked",
            "reason": "generate_prerequisite_missing",
            "generate": generate_state,
            "next": "music --generate",
        }
    return EXIT_RUN, {
        "step": "master",
        "engine": "suno",
        "decision": "run",
        "reason": "master_missing",
        "missing": [output.as_posix()],
    }


def evaluate(collection_path: Path, step: str) -> tuple[int, dict[str, object]]:
    if not collection_path.is_dir():
        raise ManifestError(f"collection path is not a directory: {collection_path}")
    if step == "prompt":
        return _evaluate_prompt(collection_path)
    if step == "lyric":
        return _evaluate_lyric(collection_path)
    if step == "generate":
        return _evaluate_generate(collection_path)
    if step == "master":
        return _evaluate_master(collection_path)
    raise ManifestError(f"unknown step: {step}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection-path", type=Path, required=True)
    parser.add_argument("--step", choices=("prompt", "lyric", "generate", "master"), required=True)
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
