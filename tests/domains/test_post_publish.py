from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.core.errors import StateSyncError
from youtube_automation.domains.collections.inventory import CollectionRecord
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.post_publish import (
    PostPublishDecision,
    PostPublishReadiness,
    PostPublishStagePolicy,
    _post_publish_readiness,
    evaluate,
    mark_complete,
    resolve_post_publish_readiness,
    verify_post_publish_completion,
)


def _collection(root: Path, name: str = "demo", *, video_id: str = "video-1") -> Path:
    collection = root / "collections" / "live" / name
    collection.mkdir(parents=True)
    (collection / "workflow-state.json").write_text(
        json.dumps(
            {
                "phase": "complete",
                "stage": "live",
                "created_at": "2026-01-01T00:00:00Z",
                "assets": {},
                "upload": {"video_id": video_id},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return collection


def test_steps_are_ordered_and_history_is_idempotent(tmp_path: Path) -> None:
    collection = _collection(tmp_path)

    assert evaluate(tmp_path, collection, "playlist-assignment") == PostPublishDecision(
        "run", "not_completed", "video-1", ()
    )
    with pytest.raises(StateSyncError, match="previous_steps_incomplete"):
        mark_complete(tmp_path, collection, "pinned-comment")

    mark_complete(tmp_path, collection, "playlist-assignment")
    mark_complete(tmp_path, collection, "playlist-assignment")
    decision = evaluate(tmp_path, collection, "playlist-assignment")

    assert decision.status == "skip"
    history = json.loads((tmp_path / "post_publish_history.json").read_text(encoding="utf-8"))
    assert list(history["videos"]["video-1"]["completed"]) == ["playlist-assignment"]


def test_history_refuses_symlink_and_malformed_documents(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    target = tmp_path / "outside.json"
    target.write_text('{"schema_version": 1, "videos": {}}\n', encoding="utf-8")
    (tmp_path / "post_publish_history.json").symlink_to(target)

    with pytest.raises(StateSyncError, match="symlink"):
        evaluate(tmp_path, collection, "playlist-assignment")


def test_cloud_readiness_selects_oldest_incomplete_live_collection(tmp_path: Path) -> None:
    newer = _collection(tmp_path, "newer", video_id="video-2")
    older = _collection(tmp_path, "older", video_id="video-1")
    newer_state = json.loads((newer / "workflow-state.json").read_text(encoding="utf-8"))
    newer_state["created_at"] = "2026-02-01T00:00:00Z"
    (newer / "workflow-state.json").write_text(json.dumps(newer_state) + "\n", encoding="utf-8")

    readiness = resolve_post_publish_readiness(tmp_path)

    assert readiness.status == "ready"
    assert readiness.collection == older.resolve()


def test_readiness_skips_live_collection_whose_phase_is_not_complete(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    state_path = collection / "workflow-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["phase"] = "publishing"
    state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")

    assert resolve_post_publish_readiness(tmp_path) == PostPublishReadiness("waiting", None)


def test_readiness_reports_invalid_shared_post_publish_history(tmp_path: Path) -> None:
    _collection(tmp_path)
    (tmp_path / "post_publish_history.json").write_text('{"schema_version": 999, "videos": {}}\n', encoding="utf-8")

    with pytest.raises(StateSyncError, match="unsupported post-publish history schema"):
        resolve_post_publish_readiness(tmp_path)


def test_post_publish_policy_selects_inventory_record_without_reading_files(tmp_path: Path) -> None:
    directory = tmp_path / "not-created"
    state = WorkflowState(
        {
            "phase": "complete",
            "stage": "live",
            "created_at": "2026-01-01T00:00:00Z",
            "upload": {"video_id": "video-1"},
        }
    )
    records = (CollectionRecord(directory, "live", state),)

    assert _post_publish_readiness(records, None, lambda _: False) == PostPublishReadiness("ready", directory)


def test_completion_requires_all_tracking_and_pinned_actual_artifact(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    for step in ("playlist-assignment", "pinned-comment", "metadata-audit"):
        mark_complete(tmp_path, collection, step)

    with pytest.raises(StateSyncError, match="pinned comment actual artifact"):
        verify_post_publish_completion(tmp_path, collection)

    (tmp_path / "pinned_comment_history.json").write_text(
        json.dumps({"schema_version": 1, "posted": {"video-1": {"posted_at": "2026-01-01T00:00:00Z"}}}) + "\n",
        encoding="utf-8",
    )
    assert verify_post_publish_completion(tmp_path, collection) == collection.resolve()


def test_readiness_waits_when_no_live_collection_needs_followup(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    for step in ("playlist-assignment", "pinned-comment", "metadata-audit"):
        mark_complete(tmp_path, collection, step)
    (tmp_path / "pinned_comment_history.json").write_text(
        json.dumps({"schema_version": 1, "posted": {"video-1": {}}}) + "\n", encoding="utf-8"
    )

    readiness = resolve_post_publish_readiness(tmp_path)

    assert readiness.status == "waiting"
    assert readiness.collection is None


def test_post_publish_stage_policy_adapts_target_prompt_completion_and_allowlist(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    policy = PostPublishStagePolicy(tmp_path, "/publish", None)

    policy.resolve()
    assert policy.waiting is False
    assert "collection 'demo'" in policy.prompt_for()
    for step in ("playlist-assignment", "pinned-comment", "metadata-audit"):
        mark_complete(tmp_path, collection, step)
    (tmp_path / "pinned_comment_history.json").write_text(
        json.dumps({"schema_version": 1, "posted": {"video-1": {}}}) + "\n", encoding="utf-8"
    )

    assert policy.verify() == "demo"
    policy.allows(tmp_path, {"post_publish_history.json", "pinned_comment_history.json"})
    with pytest.raises(StateSyncError, match="unowned path"):
        policy.allows(tmp_path, {"README.md"})
