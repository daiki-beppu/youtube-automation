"""Suno downloaded artifact の workflow-state 更新。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.suno_artifact_contracts import DOCUMENTATION_DIRNAME, SUNO_PROMPTS_JSON_FILENAME

_SUNO_CLIPS_PER_PROMPT = 2


class AtomicJsonWriter(Protocol):
    def __call__(self, target: Path, data: dict, *, prefix: str) -> None: ...


def read_pattern_count(coll_dir: Path, *, default: int | None = None) -> int | None:
    prompts_path = coll_dir / DOCUMENTATION_DIRNAME / SUNO_PROMPTS_JSON_FILENAME
    if not prompts_path.is_file():
        return default
    try:
        prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default
    if not isinstance(prompts, list):
        return default
    return len(prompts)


def expected_download_count(pattern_count: int | None, explicit_expected: int | None = None) -> int | None:
    if pattern_count is None:
        return explicit_expected
    pattern_expected = pattern_count * _SUNO_CLIPS_PER_PROMPT
    if explicit_expected is None:
        return pattern_expected
    return max(pattern_expected, explicit_expected)


def _read_existing_workflow_state(ws_path: Path) -> dict:
    if not ws_path.is_file():
        return {}
    try:
        data = json.loads(ws_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("invalid workflow-state.json") from exc
    if not isinstance(data, dict):
        raise ValueError("invalid workflow-state.json: root must be an object")
    return data


def update_workflow_state_downloaded(
    coll_dir: Path,
    *,
    file_count: int,
    suno_playlist_url: str | None = None,
    expected_file_count: int | None = None,
    atomic_json_write: AtomicJsonWriter,
) -> None:
    ws_path = CollectionPaths(coll_dir).workflow_state_path
    data = _read_existing_workflow_state(ws_path)

    planning = data.setdefault("planning", {})
    if not isinstance(planning, dict):
        planning = {}
        data["planning"] = planning
    music = planning.setdefault("music", {})
    if not isinstance(music, dict):
        music = {}
        planning["music"] = music
    if suno_playlist_url:
        music["suno_playlist_url"] = suno_playlist_url
    pattern_count = read_pattern_count(coll_dir)
    full_expected_count = expected_download_count(pattern_count)
    effective_expected_count = expected_download_count(pattern_count, expected_file_count)
    if (
        expected_file_count is not None
        and full_expected_count is not None
        and expected_file_count >= full_expected_count
    ):
        music["expected_file_count"] = expected_file_count

    assets = data.setdefault("assets", {})
    if not isinstance(assets, dict):
        assets = {}
        data["assets"] = assets
    if file_count > 0:
        if effective_expected_count is not None and file_count >= effective_expected_count:
            assets["music_downloaded"] = True
        elif effective_expected_count is None:
            assets["music_downloaded"] = True
        elif "music_downloaded" in assets:
            del assets["music_downloaded"]

    ws_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(ws_path, data, prefix=".workflow-state-")
