"""Suno downloaded artifact の workflow-state 更新。"""

from __future__ import annotations

from pathlib import Path

from youtube_automation.core.adapters.media import CollectionPaths
from youtube_automation.core.errors import WorkflowStateError
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.collections.workflow_state import update as update_workflow_state
from youtube_automation.domains.suno.downloaded.models import (
    DOCUMENTATION_DIRNAME,
    SUNO_PROMPTS_JSON_FILENAME,
    PromptEntriesReader,
)

_SUNO_CLIPS_PER_PROMPT = 2
_MISSING_REASON_KEYS = frozenset({"suno_unfulfilled", "apply_skipped"})


def read_pattern_count(
    coll_dir: Path,
    *,
    prompt_entries_reader: PromptEntriesReader,
    default: int | None = None,
) -> int | None:
    prompts_path = coll_dir / DOCUMENTATION_DIRNAME / SUNO_PROMPTS_JSON_FILENAME
    if not prompts_path.is_file():
        return default
    try:
        prompts = prompt_entries_reader(coll_dir)
    except ValueError:
        return default
    return len(prompts)


def expected_download_count(pattern_count: int | None, explicit_expected: int | None = None) -> int | None:
    if explicit_expected is not None:
        return explicit_expected
    if pattern_count is None:
        return None
    return pattern_count * _SUNO_CLIPS_PER_PROMPT


def _validate_missing_reasons(missing_reasons: dict[str, object] | None) -> dict[str, int] | None:
    if missing_reasons is None:
        return None
    if set(missing_reasons) != _MISSING_REASON_KEYS:
        raise ValueError("missing_reasons must contain suno_unfulfilled and apply_skipped")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in missing_reasons.values()):
        raise ValueError("missing_reasons values must be non-negative integers")
    return {
        "suno_unfulfilled": missing_reasons["suno_unfulfilled"],
        "apply_skipped": missing_reasons["apply_skipped"],
    }


def update_workflow_state_downloaded(
    coll_dir: Path,
    *,
    file_count: int,
    suno_playlist_url: str | None = None,
    expected_file_count: int | None = None,
    missing_reasons: dict[str, object] | None = None,
    prompt_entries_reader: PromptEntriesReader,
) -> None:
    validated_missing_reasons = _validate_missing_reasons(missing_reasons)
    ws_path = CollectionPaths(coll_dir).workflow_state_path
    pattern_count = read_pattern_count(coll_dir, prompt_entries_reader=prompt_entries_reader)
    effective_expected_count = expected_download_count(pattern_count, expected_file_count)

    def record_downloaded(state: WorkflowState) -> None:
        planning = state.get("planning") or {}
        if not isinstance(planning, dict):
            planning = {}
        music = planning.get("music") or {}
        if not isinstance(music, dict):
            music = {}
        if suno_playlist_url:
            music["suno_playlist_url"] = suno_playlist_url
        if expected_file_count is not None and expected_file_count > 0:
            music["expected_file_count"] = expected_file_count

        assets = state.get("assets") or {}
        if not isinstance(assets, dict):
            assets = {}
        if file_count > 0:
            # 部分完了も downloaded とし、不足理由を後続工程から観測可能に保つ。
            music["actual_file_count"] = file_count
            if effective_expected_count is not None:
                music["missing_file_count"] = max(0, effective_expected_count - file_count)
            download_complete = effective_expected_count is not None and file_count >= effective_expected_count
            if download_complete:
                music.pop("missing_reasons", None)
            elif validated_missing_reasons is not None:
                music["missing_reasons"] = validated_missing_reasons
            assets["music_downloaded"] = True

        planning["music"] = music
        state["planning"] = planning
        state["assets"] = assets

    try:
        update_workflow_state(ws_path, record_downloaded)
    except WorkflowStateError as error:
        if isinstance(error.__cause__, OSError) and "could not be written" in str(error):
            raise error.__cause__ from error
        raise ValueError("invalid workflow-state.json") from error
