"""MiniMax video task の再開状態を原子的に永続化する。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

_HASH_LEN = 16
_REQUIRED_KEYS = {
    "task_id",
    "model",
    "output_path",
    "input_image_sha256",
    "prompt_sha256",
    "duration_seconds",
    "aspect_ratio",
    "resolution",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_channel_root(channel_root: Path | None) -> Path:
    if channel_root is not None:
        return channel_root
    from youtube_automation.configuration import channel_dir

    return channel_dir()


def state_path(output_path: Path, *, channel_root: Path | None = None) -> Path:
    root = _resolve_channel_root(channel_root)
    key = hashlib.sha1(str(output_path.resolve()).encode()).hexdigest()[:_HASH_LEN]
    return root / "tmp" / "minimax-video-tasks" / f"{key}.json"


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
        "input_image_sha256": _sha256_file(image_path),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "duration_seconds": duration_seconds,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
    return path


def load(output_path: Path, *, channel_root: Path | None = None) -> dict[str, object] | None:
    path = state_path(output_path, channel_root=channel_root)
    if path.is_symlink():
        path.unlink(missing_ok=True)
        return None
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        path.unlink(missing_ok=True)
        return None
    if not isinstance(value, dict) or _REQUIRED_KEYS - value.keys():
        path.unlink(missing_ok=True)
        return None
    if not all(isinstance(value[key], str) for key in _REQUIRED_KEYS - {"duration_seconds"}):
        path.unlink(missing_ok=True)
        return None
    if (
        not isinstance(value["duration_seconds"], int)
        or isinstance(value["duration_seconds"], bool)
        or Path(value["output_path"]).resolve() != output_path.resolve()
    ):
        path.unlink(missing_ok=True)
        return None
    return value


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
        state["input_image_sha256"] == _sha256_file(image_path)
        and state["prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
        and state["model"] == model
        and state["duration_seconds"] == duration_seconds
        and state["aspect_ratio"] == aspect_ratio
        and state["resolution"] == resolution
    )


def clear(output_path: Path, *, channel_root: Path | None = None) -> None:
    state_path(output_path, channel_root=channel_root).unlink(missing_ok=True)
