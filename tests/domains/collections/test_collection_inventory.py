"""Collection inventory domain tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.core.errors import WorkflowStateError
from youtube_automation.domains.collections.inventory import (
    CollectionRecord,
    UnreadableWorkflowState,
    iter_collections,
)
from youtube_automation.domains.collections.workflow_state import WorkflowState


def _collection(channel_dir: Path, stage: str, name: str, payload: object = None) -> Path:
    directory = channel_dir / "collections" / stage / name
    directory.mkdir(parents=True)
    if payload is not None:
        (directory / "workflow-state.json").write_text(json.dumps(payload), encoding="utf-8")
    return directory


def test_iter_collections_returns_resolved_records_in_name_order(tmp_path: Path) -> None:
    live = _collection(tmp_path, "live", "beta", {"phase": "complete"})
    planning = _collection(tmp_path, "planning", "alpha", {"phase": "planning"})

    records = iter_collections(tmp_path)

    assert [record.directory for record in records] == [planning.resolve(), live.resolve()]
    assert [record.stage for record in records] == ["planning", "live"]
    assert all(isinstance(record, CollectionRecord) for record in records)
    assert all(isinstance(record.state, WorkflowState) for record in records)


def test_iter_collections_honors_requested_stages_and_empty_stage(tmp_path: Path) -> None:
    _collection(tmp_path, "planning", "draft", {})
    (tmp_path / "collections" / "live").mkdir(parents=True)

    assert iter_collections(tmp_path, stages=("live",)) == ()
    assert [record.directory.name for record in iter_collections(tmp_path, stages=("planning",))] == ["draft"]


def test_iter_collections_skips_private_prefixes_and_non_directories(tmp_path: Path) -> None:
    _collection(tmp_path, "planning", "_internal", {})
    _collection(tmp_path, "planning", ".hidden", {})
    visible = _collection(tmp_path, "planning", "visible", {})
    (tmp_path / "collections" / "planning" / "note.txt").write_text("ignore", encoding="utf-8")

    assert [record.directory for record in iter_collections(tmp_path)] == [visible.resolve()]


@pytest.mark.parametrize("target", ["collections", "stage", "collection"])
def test_iter_collections_rejects_symlinks(tmp_path: Path, target: str) -> None:
    real = tmp_path / "real"
    real.mkdir()
    collections = tmp_path / "collections"
    if target == "collections":
        collections.symlink_to(real, target_is_directory=True)
    elif target == "stage":
        collections.mkdir()
        (collections / "planning").symlink_to(real, target_is_directory=True)
    else:
        stage = collections / "planning"
        stage.mkdir(parents=True)
        (stage / "linked").symlink_to(real, target_is_directory=True)

    with pytest.raises(WorkflowStateError, match="symlink"):
        iter_collections(tmp_path)


@pytest.mark.parametrize("state_contents", [None, "not json", "[]"])
def test_iter_collections_represents_unreadable_state(tmp_path: Path, state_contents: str | None) -> None:
    directory = _collection(tmp_path, "planning", "broken")
    if state_contents is not None:
        (directory / "workflow-state.json").write_text(state_contents, encoding="utf-8")

    state = iter_collections(tmp_path)[0].state

    assert isinstance(state, UnreadableWorkflowState)
    assert state.path == directory.resolve() / "workflow-state.json"
    assert "workflow-state.json" in state.reason


def test_iter_collections_rejects_duplicate_names_across_stages(tmp_path: Path) -> None:
    _collection(tmp_path, "planning", "same", {})
    _collection(tmp_path, "live", "same", {})

    with pytest.raises(WorkflowStateError, match="duplicate collection name.*same"):
        iter_collections(tmp_path)


def test_iter_collections_rejects_unknown_or_repeated_stage(tmp_path: Path) -> None:
    with pytest.raises(WorkflowStateError, match="unsupported collection stage"):
        iter_collections(tmp_path, stages=("archive",))  # type: ignore[arg-type]
    with pytest.raises(WorkflowStateError, match="duplicate collection stage"):
        iter_collections(tmp_path, stages=("planning", "planning"))
