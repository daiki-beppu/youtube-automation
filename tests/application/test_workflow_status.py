from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from youtube_automation.application.workflow_status import build_workflow_status_snapshot

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _collection(root: Path, area: str, name: str, state: dict[str, object] | None) -> Path:
    collection = root / "collections" / area / name
    for directory in ("01-master", "02-Individual-music", "10-assets", "20-documentation"):
        (collection / directory).mkdir(parents=True, exist_ok=True)
    if state is not None:
        (collection / "workflow-state.json").write_text(json.dumps(state), encoding="utf-8")
    return collection


def _state(**overrides: object) -> dict[str, object]:
    state: dict[str, object] = {
        "collection_name": "Quiet <Night>",
        "stage": "planning",
        "phase": "prepared",
        "updated_at": "2026-08-06T12:00:00+00:00",
        "music_engine": "suno",
        "planning": {"generated": True},
        "assets": {
            "thumbnail": True,
            "music_prompts": True,
            "master_audio": None,
            "master_video": None,
        },
        "upload": {"video_id": None},
    }
    state.update(overrides)
    return state


def test_empty_snapshot_has_no_collections(tmp_path: Path) -> None:
    snapshot = build_workflow_status_snapshot(tmp_path, now=NOW)

    assert snapshot.generated_at == NOW
    assert snapshot.collections == ()


def test_single_collection_combines_state_and_real_artifacts(tmp_path: Path) -> None:
    collection = _collection(tmp_path, "planning", "quiet-night", _state())
    (collection / "20-documentation" / "plan_proposals.json").write_text("{}", encoding="utf-8")
    (collection / "20-documentation" / "suno-prompts.json").write_text("[]", encoding="utf-8")
    (collection / "10-assets" / "thumbnail.jpg").write_bytes(b"image")

    snapshot = build_workflow_status_snapshot(tmp_path, now=NOW)

    item = snapshot.collections[0]
    assert item.name == "Quiet <Night>"
    assert item.status == "planning"
    assert item.phase == "prepared"
    assert item.next_action == "/wf-next"
    assert item.stalled_for == "10日 0時間"
    assert {artifact.key: artifact.status for artifact in item.artifacts} == {
        "plan": "complete",
        "thumbnail": "complete",
        "music_prompt": "complete",
        "master_audio": "missing",
        "master_video": "missing",
        "publish": "missing",
    }


def test_multiple_collections_are_filterable_as_planning_live_and_complete(tmp_path: Path) -> None:
    _collection(tmp_path, "planning", "a-planning", _state(collection_name="Planning"))
    _collection(
        tmp_path,
        "live",
        "b-live",
        _state(collection_name="Live", stage="live", phase="publishing"),
    )
    _collection(
        tmp_path,
        "live",
        "c-complete",
        _state(
            collection_name="Complete",
            stage="live",
            phase="complete",
            upload={"video_id": "video-1"},
        ),
    )

    snapshot = build_workflow_status_snapshot(tmp_path, now=NOW)

    assert [(item.name, item.status) for item in snapshot.collections] == [
        ("Planning", "planning"),
        ("Live", "live"),
        ("Complete", "complete"),
    ]
    assert snapshot.collections[-1].next_action == "完了"


def test_state_artifact_mismatch_is_a_visible_blocker(tmp_path: Path) -> None:
    _collection(
        tmp_path,
        "planning",
        "missing-master",
        _state(
            phase="mastered",
            assets={
                "thumbnail": False,
                "music_prompts": False,
                "master_audio": "final.wav",
                "master_video": None,
            },
        ),
    )

    item = build_workflow_status_snapshot(tmp_path, now=NOW).collections[0]

    master_audio = next(artifact for artifact in item.artifacts if artifact.key == "master_audio")
    assert master_audio.status == "inconsistent"
    assert "final.wav" in master_audio.detail
    assert "master音源" in item.blocker
    assert item.next_action == "/wf-next"


def test_untracked_real_master_is_reported_as_inconsistent(tmp_path: Path) -> None:
    collection = _collection(tmp_path, "planning", "untracked-master", _state())
    (collection / "01-master" / "untracked.mp3").write_bytes(b"audio")

    item = build_workflow_status_snapshot(tmp_path, now=NOW).collections[0]

    master_audio = next(artifact for artifact in item.artifacts if artifact.key == "master_audio")
    assert master_audio.status == "inconsistent"
    assert "untracked.mp3" in master_audio.detail


def test_complete_phase_without_video_id_is_reported_as_inconsistent(tmp_path: Path) -> None:
    _collection(tmp_path, "live", "missing-publish", _state(stage="live", phase="complete"))

    item = build_workflow_status_snapshot(tmp_path, now=NOW).collections[0]

    publish = next(artifact for artifact in item.artifacts if artifact.key == "publish")
    assert publish.status == "inconsistent"
    assert item.next_action == "/wf-next"


def test_invalid_state_is_reported_without_modifying_source(tmp_path: Path) -> None:
    collection = _collection(tmp_path, "planning", "broken", None)
    state_path = collection / "workflow-state.json"
    state_path.write_text("{broken", encoding="utf-8")
    before = state_path.read_bytes()

    item = build_workflow_status_snapshot(tmp_path, now=NOW).collections[0]

    assert item.status == "planning"
    assert item.phase == "不明"
    assert "workflow-state.json" in item.blocker
    assert item.next_action == "/wf-new"
    assert state_path.read_bytes() == before
