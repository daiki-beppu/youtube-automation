"""Suno downloaded workflow missing-reason contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.domains.suno.downloaded.workflow import update_workflow_state_downloaded


def _write_json(target: Path, data: dict, *, prefix: str) -> None:
    target.write_text(json.dumps(data), encoding="utf-8")


def _read_music(collection_dir: Path) -> dict:
    state = json.loads((collection_dir / "workflow-state.json").read_text(encoding="utf-8"))
    return state["planning"]["music"]


def test_should_store_missing_reasons_as_non_negative_integers(tmp_path: Path) -> None:
    update_workflow_state_downloaded(
        tmp_path,
        file_count=2,
        missing_reasons={"suno_unfulfilled": 1, "apply_skipped": 1},
        prompt_entries_reader=lambda _collection_dir: [],
        atomic_json_write=_write_json,
    )

    assert _read_music(tmp_path)["missing_reasons"] == {
        "suno_unfulfilled": 1,
        "apply_skipped": 1,
    }


@pytest.mark.parametrize("key", ["suno_unfulfilled", "apply_skipped"])
@pytest.mark.parametrize("invalid_value", [-1, True, 1.5, "1"])
def test_should_reject_invalid_missing_reason_counts(tmp_path: Path, key: str, invalid_value: object) -> None:
    missing_reasons: dict[str, object] = {
        "suno_unfulfilled": 1,
        "apply_skipped": 1,
    }
    missing_reasons[key] = invalid_value

    with pytest.raises(ValueError, match="missing_reasons values must be non-negative integers"):
        update_workflow_state_downloaded(
            tmp_path,
            file_count=2,
            expected_file_count=4,
            missing_reasons=missing_reasons,
            prompt_entries_reader=lambda _collection_dir: [],
            atomic_json_write=_write_json,
        )

    assert not (tmp_path / "workflow-state.json").exists()


@pytest.mark.parametrize(
    "missing_reasons",
    [
        {"suno_unfulfilled": 1},
        {"suno_unfulfilled": 1, "apply_skipped": 0, "other": 0},
    ],
)
def test_should_reject_invalid_missing_reason_shape(tmp_path: Path, missing_reasons: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="missing_reasons must contain suno_unfulfilled and apply_skipped"):
        update_workflow_state_downloaded(
            tmp_path,
            file_count=2,
            expected_file_count=4,
            missing_reasons=missing_reasons,
            prompt_entries_reader=lambda _collection_dir: [],
            atomic_json_write=_write_json,
        )

    assert not (tmp_path / "workflow-state.json").exists()


def test_should_remove_previous_missing_reasons_when_download_is_complete(tmp_path: Path) -> None:
    (tmp_path / "workflow-state.json").write_text(
        json.dumps(
            {
                "planning": {
                    "music": {
                        "missing_reasons": {
                            "suno_unfulfilled": 2,
                            "apply_skipped": 0,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    update_workflow_state_downloaded(
        tmp_path,
        file_count=4,
        expected_file_count=4,
        prompt_entries_reader=lambda _collection_dir: [],
        atomic_json_write=_write_json,
    )

    music = _read_music(tmp_path)
    assert music["missing_file_count"] == 0
    assert "missing_reasons" not in music


def test_should_preserve_existing_caller_path_without_missing_reasons(tmp_path: Path) -> None:
    update_workflow_state_downloaded(
        tmp_path,
        file_count=2,
        expected_file_count=4,
        prompt_entries_reader=lambda _collection_dir: [],
        atomic_json_write=_write_json,
    )

    music = _read_music(tmp_path)
    assert music["actual_file_count"] == 2
    assert music["missing_file_count"] == 2
    assert "missing_reasons" not in music
