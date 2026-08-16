from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.core.errors import StateSyncError
from youtube_automation.domains.cloud_planning import (
    PlanningReadiness,
    resolve_planning_readiness,
    verify_planning_completion,
)


def _state(root: Path, name: str, *, phase: str, created_at: str, engine: str = "suno") -> Path:
    collection = root / "collections" / "planning" / name
    collection.mkdir(parents=True)
    (collection / "workflow-state.json").write_text(
        json.dumps(
            {
                "phase": phase,
                "created_at": created_at,
                "planning": {"generated": phase != "planning", "music": {"engine": engine}},
                "assets": {"music_prompts": phase != "planning"},
                "upload": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return collection


def test_readiness_selects_new_planning_when_no_unfinished_collection_exists(tmp_path: Path) -> None:
    assert resolve_planning_readiness(tmp_path) == PlanningReadiness("ready", None)


def test_readiness_selects_oldest_planning_collection(tmp_path: Path) -> None:
    newer = _state(tmp_path, "newer", phase="planning", created_at="2026-02-02T00:00:00Z")
    older = _state(tmp_path, "older", phase="planning", created_at="2026-01-01T00:00:00Z")

    assert resolve_planning_readiness(tmp_path) == PlanningReadiness("ready", older.resolve())
    assert newer.exists()


def test_readiness_waits_when_oldest_active_collection_has_left_planning(tmp_path: Path) -> None:
    prepared = _state(tmp_path, "prepared", phase="prepared", created_at="2026-01-01T00:00:00Z")
    _state(tmp_path, "planning", phase="planning", created_at="2026-02-01T00:00:00Z")

    assert resolve_planning_readiness(tmp_path) == PlanningReadiness("waiting", prepared.resolve())


def test_completion_requires_prepared_state_and_engine_prompt_pair(tmp_path: Path) -> None:
    collection = _state(tmp_path, "demo", phase="prepared", created_at="2026-01-01T00:00:00Z")
    docs = collection / "20-documentation"
    docs.mkdir()
    (docs / "plan_proposals.json").write_text("{}\n", encoding="utf-8")
    (docs / "plan_proposals.html").write_text("<!doctype html>\n", encoding="utf-8")
    (docs / "suno-prompts.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(StateSyncError, match="prompt pair"):
        verify_planning_completion(tmp_path, collection)

    (docs / "suno-prompts.html").write_text("<!doctype html>\n", encoding="utf-8")
    assert verify_planning_completion(tmp_path, collection) == collection.resolve()


def test_completion_resolves_exactly_one_new_collection(tmp_path: Path) -> None:
    first = _state(tmp_path, "first", phase="prepared", created_at="2026-01-01T00:00:00Z")
    second = _state(tmp_path, "second", phase="prepared", created_at="2026-01-02T00:00:00Z")
    for collection in (first, second):
        docs = collection / "20-documentation"
        docs.mkdir()
        (docs / "plan_proposals.json").write_text("{}\n", encoding="utf-8")
        (docs / "plan_proposals.html").write_text("<!doctype html>\n", encoding="utf-8")
        (docs / "suno-prompts.json").write_text("{}\n", encoding="utf-8")
        (docs / "suno-prompts.html").write_text("<!doctype html>\n", encoding="utf-8")

    with pytest.raises(StateSyncError, match="exactly one"):
        verify_planning_completion(tmp_path, None)
