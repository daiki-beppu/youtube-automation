"""fal queue request の再開状態を原子的に永続化する。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

_HASH_LEN = 16
_REQUIRED_KEYS = {
    "request_id",
    "response_url",
    "status_url",
    "cancel_url",
    "submitted_at",
    "model",
    "output_path",
    "input_image_sha256",
    "prompt_sha256",
    "duration_seconds",
    "resolution",
    "prompt_expansion_mode",
}
_INTEGER_KEYS = {"duration_seconds"}


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
    return root / "tmp" / "fal-video-tasks" / f"{key}.json"


def save(
    output_path: Path,
    image_path: Path,
    *,
    request_id: str,
    response_url: str,
    status_url: str,
    cancel_url: str,
    submitted_at: str,
    model: str,
    prompt: str,
    duration_seconds: int,
    resolution: str,
    prompt_expansion_mode: str,
    channel_root: Path | None = None,
) -> Path:
    """元画像と生成条件を queue request の再開情報とともに保存する。"""
    path = state_path(output_path, channel_root=channel_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "request_id": request_id,
        "response_url": response_url,
        "status_url": status_url,
        "cancel_url": cancel_url,
        "submitted_at": submitted_at,
        "model": model,
        "output_path": str(output_path.resolve()),
        "input_image_sha256": _sha256_file(image_path),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "duration_seconds": duration_seconds,
        "resolution": resolution,
        "prompt_expansion_mode": prompt_expansion_mode,
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
    return path


def load(output_path: Path, *, channel_root: Path | None = None) -> dict[str, object] | None:
    """有効な state を返し、壊れた state は削除する。"""
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
    if not all(isinstance(value[key], str) for key in _REQUIRED_KEYS - _INTEGER_KEYS):
        path.unlink(missing_ok=True)
        return None
    duration = value["duration_seconds"]
    if (
        not isinstance(duration, int)
        or isinstance(duration, bool)
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
    resolution: str,
    prompt_expansion_mode: str,
) -> bool:
    """state の生成入力が現在の生成条件と一致するか判定する。"""
    return (
        state["input_image_sha256"] == _sha256_file(image_path)
        and state["prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
        and state["model"] == model
        and state["duration_seconds"] == duration_seconds
        and state["resolution"] == resolution
        and state["prompt_expansion_mode"] == prompt_expansion_mode
    )


def clear(output_path: Path, *, channel_root: Path | None = None) -> None:
    """保存済み state を削除する。"""
    state_path(output_path, channel_root=channel_root).unlink(missing_ok=True)
