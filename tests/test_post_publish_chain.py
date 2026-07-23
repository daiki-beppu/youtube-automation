"""`/post-publish` manifest、履歴、skill 委譲の契約テスト."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / ".claude" / "skills" / "post-publish"
SCRIPT = SKILL_DIR / "references" / "post-publish-chain-state.py"
MANIFEST = SKILL_DIR / "references" / "post-publish-chain-manifest.json"
STEPS = ("community-post", "pinned-comment", "metadata-audit")


def _resolve_approval_gate(gate: dict[str, bool]) -> bool:
    if "skip" in gate and "enabled" in gate:
        raise ValueError("approvalGate.skip と approvalGate.enabled は同時指定できません")
    if "skip" in gate:
        return gate["skip"]
    if "enabled" in gate:
        return not gate["enabled"]
    raise ValueError("approvalGate.skip または legacy enabled が必要です")


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("post_publish_chain_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def state() -> ModuleType:
    return _load_module()


def _collection(
    root: Path,
    name: str = "20260718-test",
    video_id: str = "video-123",
    publish_at: str | None = None,
) -> Path:
    collection = root / "collections" / "live" / name
    collection.mkdir(parents=True)
    upload = {"video_id": video_id}
    if publish_at is not None:
        upload["publish_at"] = publish_at
    (collection / "workflow-state.json").write_text(json.dumps({"upload": upload}), encoding="utf-8")
    return collection


def test_manifest_declares_ordered_gated_chain() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["chainId"] == "post-publish"
    assert [step["id"] for step in manifest["steps"]] == list(STEPS)
    assert [step["skill"] for step in manifest["steps"]] == list(STEPS)
    assert len({step["id"] for step in manifest["steps"]}) == len(STEPS)
    assert all(step["approvalGate"]["skip"] is True for step in manifest["steps"])
    assert all("enabled" not in step["approvalGate"] for step in manifest["steps"])
    assert all(".skip_approvals." in step["approvalGate"]["configPath"] for step in manifest["steps"])
    assert {step["idempotency"]["script"] for step in manifest["steps"]} == {"references/post-publish-chain-state.py"}


@pytest.mark.parametrize(("enabled", "expected_skip"), [(False, True), (True, False)])
def test_legacy_manifest_enabled_is_resolved_as_inverse(enabled: bool, expected_skip: bool) -> None:
    assert _resolve_approval_gate({"enabled": enabled}) is expected_skip


def test_manifest_gate_rejects_skip_and_enabled_together() -> None:
    with pytest.raises(ValueError, match="同時指定"):
        _resolve_approval_gate({"skip": True, "enabled": False})


def test_history_enforces_order_and_skips_completed_steps(tmp_path: Path, state: ModuleType) -> None:
    collection = _collection(tmp_path)

    blocked_code, blocked = state.evaluate(tmp_path, collection, "pinned-comment")
    run_code, runnable = state.evaluate(tmp_path, collection, "community-post")
    completed = state.mark_complete(tmp_path, collection, "community-post")
    skip_code, skipped = state.evaluate(tmp_path, collection, "community-post")
    next_code, next_step = state.evaluate(tmp_path, collection, "pinned-comment")

    assert blocked_code == state.EXIT_BLOCKED
    assert blocked["reason"] == "previous_steps_incomplete:community-post"
    assert run_code == state.EXIT_RUN
    assert runnable["video_id"] == "video-123"
    assert completed["decision"] == "skip"
    assert skip_code == state.EXIT_SKIP
    assert skipped["reason"] == "already_completed"
    assert next_code == state.EXIT_RUN
    assert next_step["completed_steps"] == ["community-post"]


def test_history_is_keyed_by_video_id_across_collection_paths(tmp_path: Path, state: ModuleType) -> None:
    first = _collection(tmp_path, "20260718-first", "same-video")
    second = _collection(tmp_path, "20260718-second", "same-video")
    state.mark_complete(tmp_path, first, "community-post")

    code, result = state.evaluate(tmp_path, second, "community-post")

    assert code == state.EXIT_SKIP
    assert result["video_id"] == "same-video"


def test_mark_complete_records_all_steps_atomically(tmp_path: Path, state: ModuleType) -> None:
    collection = _collection(tmp_path)
    for step in STEPS:
        state.mark_complete(tmp_path, collection, step)

    history = json.loads((tmp_path / "post_publish_history.json").read_text(encoding="utf-8"))
    assert history["schema_version"] == 1
    assert list(history["videos"]["video-123"]["completed"]) == list(STEPS)
    assert not list(tmp_path.glob(".post_publish_history.json.*.tmp"))


def test_corrupt_history_fails_closed(tmp_path: Path, state: ModuleType) -> None:
    collection = _collection(tmp_path)
    (tmp_path / "post_publish_history.json").write_text(
        json.dumps({"schema_version": 1, "videos": {"video-123": {"completed": ["community-post"]}}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="completed は object"):
        state.evaluate(tmp_path, collection, "community-post")


def test_future_publish_records_pending_without_completing_pinned_step(tmp_path: Path, state: ModuleType) -> None:
    collection = _collection(tmp_path, publish_at="2026-07-24T11:00:00Z")
    state.mark_complete(tmp_path, collection, "community-post")

    code, pending = state.evaluate(
        tmp_path,
        collection,
        "pinned-comment",
        now=datetime(2026, 7, 24, 10, 0, tzinfo=UTC),
    )
    recorded = state.mark_pending_until_publish(
        tmp_path,
        collection,
        "pinned-comment",
        now=datetime(2026, 7, 24, 10, 0, tzinfo=UTC),
    )

    assert code == state.EXIT_PENDING
    assert pending["decision"] == "pending_until_publish"
    assert pending["pending_until"] == "2026-07-24T11:00:00+00:00"
    assert recorded["decision"] == "pending_until_publish"
    history = json.loads((tmp_path / "post_publish_history.json").read_text(encoding="utf-8"))
    video = history["videos"]["video-123"]
    assert video["pending"]["pinned-comment"] == "2026-07-24T11:00:00+00:00"
    assert "pinned-comment" not in video["completed"]


def test_publish_time_reached_resumes_same_video_and_clears_pending_on_complete(
    tmp_path: Path,
    state: ModuleType,
) -> None:
    collection = _collection(tmp_path, publish_at="2026-07-24T11:00:00Z")
    state.mark_complete(tmp_path, collection, "community-post")
    state.mark_pending_until_publish(
        tmp_path,
        collection,
        "pinned-comment",
        now=datetime(2026, 7, 24, 10, 0, tzinfo=UTC),
    )

    code, runnable = state.evaluate(
        tmp_path,
        collection,
        "pinned-comment",
        now=datetime(2026, 7, 24, 11, 1, tzinfo=UTC),
    )
    assert code == state.EXIT_RUN
    assert runnable["video_id"] == "video-123"

    state.mark_complete(
        tmp_path,
        collection,
        "pinned-comment",
        now=datetime(2026, 7, 24, 11, 1, tzinfo=UTC),
    )
    history = json.loads((tmp_path / "post_publish_history.json").read_text(encoding="utf-8"))
    assert "pinned-comment" not in history["videos"]["video-123"]["pending"]


def test_child_skills_support_chain_and_standalone_invocation() -> None:
    for name in STEPS:
        text = (ROOT / ".claude" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert "/post-publish" in text
        assert "単独" in text

    upload = (ROOT / ".claude" / "skills" / "video-upload" / "SKILL.md").read_text(encoding="utf-8")
    assert "workflow.post_publish.configured" in upload
    assert "/post-publish" in upload
