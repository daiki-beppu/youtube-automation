from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.core.errors import StateSyncError, ValidationError
from youtube_automation.domains.cloud_planning import (
    PlanningReadiness,
    PlanningStagePolicy,
    _planning_states,
    resolve_planning_readiness,
    validate_planning_changes,
    verify_planning_completion,
)
from youtube_automation.domains.collections.inventory import CollectionRecord
from youtube_automation.domains.collections.workflow_state import WorkflowState


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


def test_planning_policy_projects_inventory_records_without_reading_files(tmp_path: Path) -> None:
    directory = tmp_path / "not-created"
    state = WorkflowState({"phase": "planning", "created_at": "2026-01-01T00:00:00Z"})

    assert _planning_states((CollectionRecord(directory, "planning", state),)) == [(directory, state)]


def test_readiness_selects_oldest_planning_collection(tmp_path: Path) -> None:
    newer = _state(tmp_path, "newer", phase="planning", created_at="2026-02-02T00:00:00Z")
    older = _state(tmp_path, "older", phase="planning", created_at="2026-01-01T00:00:00Z")

    assert resolve_planning_readiness(tmp_path) == PlanningReadiness("ready", older.resolve())
    assert newer.exists()


def test_readiness_waits_when_oldest_active_collection_has_left_planning(tmp_path: Path) -> None:
    prepared = _state(tmp_path, "prepared", phase="prepared", created_at="2026-01-01T00:00:00Z")
    _state(tmp_path, "planning", phase="planning", created_at="2026-02-01T00:00:00Z")

    assert resolve_planning_readiness(tmp_path) == PlanningReadiness("waiting", prepared.resolve())


def test_readiness_skips_collection_whose_state_is_not_created_yet(tmp_path: Path) -> None:
    (tmp_path / "collections" / "planning" / "initializing").mkdir(parents=True)
    active = _state(tmp_path, "active", phase="planning", created_at="2026-01-01T00:00:00Z")

    assert resolve_planning_readiness(tmp_path) == PlanningReadiness("ready", active.resolve())


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


def test_planning_stage_policy_adapts_readiness_completion_and_allowlist(tmp_path: Path) -> None:
    collection = _state(tmp_path, "demo", phase="planning", created_at="2026-01-01T00:00:00Z")
    policy = PlanningStagePolicy(tmp_path, "/wf-new --auto")

    policy.resolve()
    assert policy.waiting is False
    assert policy.prompt_for() == "/wf-new --auto"

    state_path = collection / "workflow-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(phase="prepared")
    state["planning"]["generated"] = True
    state["assets"]["music_prompts"] = True
    state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
    docs = collection / "20-documentation"
    docs.mkdir()
    for name in ("plan_proposals.json", "plan_proposals.html", "suno-prompts.json", "suno-prompts.html"):
        (docs / name).write_text("{}\n", encoding="utf-8")

    assert policy.verify() == "demo"
    policy.allows(tmp_path, {"collections/planning/demo/workflow-state.json"})
    with pytest.raises(StateSyncError, match="unowned path"):
        policy.allows(tmp_path, {"README.md"})


def test_planning_stage_policy_rejects_media_handoff_before_any_side_effect(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="media handoff を受け付けません"):
        PlanningStagePolicy(tmp_path, "/wf-new --auto", object())


def test_change_allowlist_scopes_postmortem_to_channel_directory(tmp_path: Path) -> None:
    collection = tmp_path / "channels" / "focus" / "collections" / "planning" / "demo"

    validate_planning_changes(
        tmp_path,
        collection,
        {"channels/focus/collections/live/older/20-documentation/postmortem.md"},
    )

    with pytest.raises(StateSyncError, match="unowned path"):
        validate_planning_changes(
            tmp_path,
            collection,
            {"collections/live/older/20-documentation/postmortem.md"},
        )
