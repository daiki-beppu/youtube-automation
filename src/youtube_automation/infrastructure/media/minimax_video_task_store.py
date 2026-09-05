"""MiniMax video task の再開状態を原子的に永続化する。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from youtube_automation.infrastructure.media._task_store_support import (
    load_state,
    resolve_channel_root,
    sha256_file,
    state_file,
    write_state,
)

_DIRECTORY = "minimax-video-tasks"
_REQUIRED_KEYS = frozenset(
    {
        "task_id",
        "model",
        "output_path",
        "input_image_sha256",
        "prompt_sha256",
        "duration_seconds",
        "aspect_ratio",
        "resolution",
    }
)


def _resolve_channel_root(channel_root: Path | None) -> Path:
    return resolve_channel_root(channel_root)


def state_path(output_path: Path, *, channel_root: Path | None = None) -> Path:
    return state_file(output_path, root=_resolve_channel_root(channel_root), directory=_DIRECTORY)


def save(
    output_path: Path,
    image_path: Path,
    *,
    task_id: str,
    model: str,
    prompt: str,
    duration_seconds: int,
    aspect_ratio: str,
    resolution: str,
    channel_root: Path | None = None,
) -> Path:
    path = state_path(output_path, channel_root=channel_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "task_id": task_id,
        "model": model,
        "output_path": str(output_path.resolve()),
        "input_image_sha256": sha256_file(image_path),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "duration_seconds": duration_seconds,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
    }
    write_state(path, data)
    return path


def load(output_path: Path, *, channel_root: Path | None = None) -> dict[str, object] | None:
    path = state_path(output_path, channel_root=channel_root)
    return load_state(path, output_path, required_keys=_REQUIRED_KEYS)


def matches(
    state: dict[str, object],
    image_path: Path,
    *,
    model: str,
    prompt: str,
    duration_seconds: int,
    aspect_ratio: str,
    resolution: str,
) -> bool:
    return (
        state["input_image_sha256"] == sha256_file(image_path)
        and state["prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
        and state["model"] == model
        and state["duration_seconds"] == duration_seconds
        and state["aspect_ratio"] == aspect_ratio
        and state["resolution"] == resolution
    )


def clear(output_path: Path, *, channel_root: Path | None = None) -> None:
    state_path(output_path, channel_root=channel_root).unlink(missing_ok=True)
