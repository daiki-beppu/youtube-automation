"""fal queue request の再開状態を原子的に永続化する。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from youtube_automation.core.errors import GeneratorError
from youtube_automation.infrastructure.media._task_store_support import (
    load_state,
    resolve_channel_root,
    sha256_file,
    state_file,
    write_state,
)

_DIRECTORY = "fal-video-tasks"
_REQUIRED_KEYS = frozenset(
    {
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
        "input_canvas",
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
    input_canvas: str,
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
        "input_image_sha256": sha256_file(image_path),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "duration_seconds": duration_seconds,
        "resolution": resolution,
        "prompt_expansion_mode": prompt_expansion_mode,
        "input_canvas": input_canvas,
    }
    write_state(path, data)
    return path


def raw_video_path(output_path: Path, *, channel_root: Path | None = None) -> Path:
    """最終公開前の生動画を再開 state と同じキーで保持する。"""
    return state_path(output_path, channel_root=channel_root).with_suffix(".mp4")


def save_result(output_path: Path, result: dict[str, object], *, channel_root: Path | None = None) -> None:
    """ダウンロード済みの結果を保存し、API の失効後も後処理を再開可能にする。"""
    state = load(output_path, channel_root=channel_root)
    if state is None:
        raise GeneratorError("fal の再開 state が見つかりません")
    state["result"] = result
    write_state(state_path(output_path, channel_root=channel_root), state)


def load(output_path: Path, *, channel_root: Path | None = None) -> dict[str, object] | None:
    """有効な state を返し、壊れた state は削除する。"""
    path = state_path(output_path, channel_root=channel_root)
    return load_state(path, output_path, required_keys=_REQUIRED_KEYS)


def matches(
    state: dict[str, object],
    image_path: Path,
    *,
    model: str,
    prompt: str,
    duration_seconds: int,
    resolution: str,
    prompt_expansion_mode: str,
    input_canvas: str,
) -> bool:
    """state の生成入力が現在の生成条件と一致するか判定する。"""
    return (
        state["input_image_sha256"] == sha256_file(image_path)
        and state["prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
        and state["model"] == model
        and state["duration_seconds"] == duration_seconds
        and state["resolution"] == resolution
        and state["prompt_expansion_mode"] == prompt_expansion_mode
        and state["input_canvas"] == input_canvas
    )


def clear(output_path: Path, *, channel_root: Path | None = None) -> None:
    """保存済み state を削除する。"""
    raw_video_path(output_path, channel_root=channel_root).unlink(missing_ok=True)
    state_path(output_path, channel_root=channel_root).unlink(missing_ok=True)
