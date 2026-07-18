"""`/automation-run` の状態選択・安全停止・再開契約テスト。"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / ".claude" / "skills" / "automation-run"
SCRIPT = SKILL_DIR / "references" / "automation-run-state.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("automation_run_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runner() -> ModuleType:
    return _load_module()


def _collection(
    root: Path,
    name: str = "20260718-test",
    *,
    stage: str = "planning",
    phase: str = "prepared",
    engine: str = "suno",
    assets: dict | None = None,
    upload: dict | None = None,
    music: dict | None = None,
) -> Path:
    collection = root / "collections" / stage / name
    (collection / "01-master").mkdir(parents=True)
    (collection / "02-Individual-music").mkdir()
    (collection / "20-documentation").mkdir()
    (collection / "20-documentation" / "suno-prompts.json").write_text(
        json.dumps([{"name": "prompt-1"}, {"name": "prompt-2"}]), encoding="utf-8"
    )
    state = {
        "collection_name": name,
        "created_at": f"2026-07-18T00:00:{name[-1:] if name[-1:].isdigit() else '00'}Z",
        "stage": stage,
        "phase": phase,
        "music_engine": engine,
        "track_count": 2,
        "planning": {"music": {"engine": engine, **(music or {})}},
        "assets": {
            "music_prompts": True,
            "music_downloaded": False,
            "raw_master": None,
            "master_audio": None,
            "master_video": None,
            "description": False,
            **(assets or {}),
        },
        "upload": {"video_id": None, "video_url": None, **(upload or {})},
    }
    (collection / "workflow-state.json").write_text(json.dumps(state), encoding="utf-8")
    return collection


def _config(
    runner: ModuleType,
    *,
    publish: bool = False,
    post_publish: bool = False,
    skip_audio_approval: bool = True,
    skip_upload_approval: bool = True,
):
    return runner.RunnerConfig(
        allow_external_publish=publish,
        post_publish_configured=post_publish,
        skip_audio_approval=skip_audio_approval,
        skip_upload_approval=skip_upload_approval,
    )


def _write_minimal_config(root: Path, *, publish: bool) -> None:
    sections = {
        "meta.json": {
            "channel": {
                "name": "Automation Run Test",
                "short": "ART",
                "youtube_handle": "@automationruntest",
                "url": "https://youtube.com/@automationruntest",
                "tagline": "test",
            }
        },
        "content.json": {
            "genre": {"primary": "ambient", "style": "soft", "context": "focus"},
            "tags": {"base": ["ambient"], "themes": {}},
            "descriptions": {"opening": "test", "perfect_for": ["focus"], "hashtags": ["#ambient"]},
            "title": {"template": "{theme}"},
        },
        "youtube.json": {"youtube": {"category_id": "10", "privacy_status": "public", "language": "en"}},
        "workflow.json": {
            "workflow": {
                "scheduled_automation": {"allow_external_publish": publish},
                "post-publish": {"approval_gates": {}},
            }
        },
    }
    for name, value in sections.items():
        path = root / "config" / "channel" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")


def test_runner_config_is_loaded_from_explicit_channel_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: ModuleType
) -> None:
    channel = tmp_path / "channel"
    _write_minimal_config(channel, publish=True)
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path / "wrong-channel"))

    config = runner._load_runner_config(channel)

    assert config.allow_external_publish is True
    assert config.post_publish_configured is True


def test_selects_oldest_unfinished_planning_collection(tmp_path: Path, runner: ModuleType) -> None:
    newer = _collection(tmp_path, "20260718-newer")
    older = _collection(tmp_path, "20260717-older")

    selected = runner.select_collection(tmp_path)

    assert selected == older
    assert selected != newer


def test_suno_requires_strict_download_contract_before_masterup(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(
        tmp_path,
        assets={"music_downloaded": True},
        music={"suno_playlist_url": "https://suno.com/playlist/test", "expected_file_count": 4},
    )
    for index in range(3):
        (collection / "02-Individual-music" / f"{index}.wav").touch()

    decision = runner.evaluate_collection(tmp_path, collection, _config(runner))

    assert decision["action"] == "suno-helper"
    assert decision["reason"] == "suno_artifacts_incomplete"


def test_suno_downloaded_routes_to_masterup_without_regeneration(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(
        tmp_path,
        assets={"music_downloaded": True},
        music={"suno_playlist_url": "https://suno.com/playlist/test", "expected_file_count": 4},
    )
    for index in range(4):
        (collection / "02-Individual-music" / f"{index}.wav").touch()

    decision = runner.evaluate_collection(tmp_path, collection, _config(runner))

    assert decision["action"] == "masterup"
    assert decision["reason"] == "suno_download_complete"


def test_suno_rejects_expected_count_below_prompt_clip_count(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(
        tmp_path,
        assets={"music_downloaded": True},
        music={"suno_playlist_url": "https://suno.com/playlist/test", "expected_file_count": 1},
    )
    (collection / "02-Individual-music" / "only.wav").touch()

    decision = runner.evaluate_collection(tmp_path, collection, _config(runner))

    assert decision["action"] == "suno-helper"
    assert decision["reason"] == "suno_artifacts_incomplete"


def test_suno_rejects_external_music_directory_symlink(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(
        tmp_path,
        assets={"music_downloaded": True},
        music={"suno_playlist_url": "https://suno.com/playlist/test", "expected_file_count": 4},
    )
    music_dir = collection / "02-Individual-music"
    music_dir.rmdir()
    external = tmp_path / "external-music"
    external.mkdir()
    for index in range(4):
        (external / f"{index}.wav").touch()
    music_dir.symlink_to(external, target_is_directory=True)

    decision = runner.evaluate_collection(tmp_path, collection, _config(runner))

    assert decision["action"] == "suno-helper"


def test_lyria_uses_only_lyria_path(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(tmp_path, engine="lyria")

    decision = runner.evaluate_collection(tmp_path, collection, _config(runner))

    assert decision["action"] == "lyria"


def test_recorded_raw_master_is_not_regenerated_when_file_is_missing(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(tmp_path, engine="lyria", assets={"raw_master": "raw.wav"})

    decision = runner.evaluate_collection(tmp_path, collection, _config(runner))

    assert decision["action"] == "blocked"
    assert decision["reason"] == "raw_master_missing"
    assert decision["resume_action"] == "wf-next"


def test_audio_approval_gate_stops_headless_progress(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(tmp_path, engine="lyria", assets={"raw_master": "raw.wav"})
    (collection / "01-master" / "raw.wav").touch()

    decision = runner.evaluate_collection(
        tmp_path,
        collection,
        _config(runner, skip_audio_approval=False),
    )

    assert decision["action"] == "blocked"
    assert decision["reason"] == "audio_approval_required"


def test_local_publish_artifacts_can_be_built_without_publish_permission(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(
        tmp_path,
        phase="mastered",
        assets={"raw_master": "master.wav", "master_audio": "master.wav"},
    )
    (collection / "01-master" / "master.wav").touch()

    decision = runner.evaluate_collection(tmp_path, collection, _config(runner, publish=False))

    assert decision["action"] == "wf-next-local"
    assert decision["allow_external_publish"] is False


def test_publish_is_blocked_after_local_artifacts_when_not_allowed(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(
        tmp_path,
        phase="publishing",
        assets={
            "raw_master": "master.wav",
            "master_audio": "master.wav",
            "master_video": "video.mp4",
            "description": True,
        },
    )
    (collection / "01-master" / "master.wav").touch()
    (collection / "01-master" / "video.mp4").touch()
    (collection / "20-documentation" / "descriptions.md").touch()

    decision = runner.evaluate_collection(tmp_path, collection, _config(runner, publish=False))

    assert decision["action"] == "blocked"
    assert decision["reason"] == "external_publish_disabled"
    assert decision["resume_action"] == "wf-next"


def test_publish_permission_routes_once_through_wf_next(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(
        tmp_path,
        phase="publishing",
        assets={
            "raw_master": "master.wav",
            "master_audio": "master.wav",
            "master_video": "video.mp4",
            "description": True,
        },
    )
    (collection / "01-master" / "master.wav").touch()
    (collection / "01-master" / "video.mp4").touch()
    (collection / "20-documentation" / "descriptions.md").touch()

    decision = runner.evaluate_collection(tmp_path, collection, _config(runner, publish=True))

    assert decision["action"] == "wf-next"
    assert decision["reason"] == "publish_ready"


def test_upload_approval_gate_stops_headless_publish(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(
        tmp_path,
        phase="publishing",
        assets={
            "raw_master": "master.wav",
            "master_audio": "master.wav",
            "master_video": "video.mp4",
            "description": True,
        },
    )
    (collection / "01-master" / "master.wav").touch()
    (collection / "01-master" / "video.mp4").touch()
    (collection / "20-documentation" / "descriptions.md").touch()

    decision = runner.evaluate_collection(
        tmp_path,
        collection,
        _config(runner, publish=True, skip_upload_approval=False),
    )

    assert decision["action"] == "blocked"
    assert decision["reason"] == "upload_approval_required"


def test_complete_upload_runs_post_publish_only_until_history_is_complete(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(
        tmp_path,
        stage="live",
        phase="complete",
        assets={"master_video": "video.mp4", "description": True},
        upload={"video_id": "video-123", "video_url": "https://youtu.be/video-123"},
    )
    first = runner.evaluate_collection(tmp_path, collection, _config(runner, publish=True, post_publish=True))
    (tmp_path / "post_publish_history.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "videos": {
                    "video-123": {
                        "completed": {
                            "community-post": "done",
                            "pinned-comment": "done",
                            "metadata-audit": "done",
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    second = runner.evaluate_collection(tmp_path, collection, _config(runner, publish=True, post_publish=True))

    assert first["action"] == "post-publish"
    assert second["action"] == "complete"


def test_post_publish_is_blocked_without_external_publish_permission(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(
        tmp_path,
        stage="live",
        phase="complete",
        upload={"video_id": "video-123", "video_url": "https://youtu.be/video-123"},
    )

    decision = runner.evaluate_collection(tmp_path, collection, _config(runner, publish=False, post_publish=True))

    assert decision["action"] == "blocked"
    assert decision["reason"] == "external_publish_disabled"
    assert decision["resume_action"] == "post-publish"


def test_upload_id_in_non_complete_state_reconciles_matching_tracking(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(tmp_path, phase="publishing", upload={"video_id": "already-uploaded"})
    (collection / "20-documentation" / "upload_tracking.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "status": "completed",
                "complete_collection": {"status": "completed", "video_id": "already-uploaded"},
            }
        ),
        encoding="utf-8",
    )

    decision = runner.evaluate_collection(tmp_path, collection, _config(runner, publish=True))

    assert decision["action"] == "wf-next"
    assert decision["reason"] == "upload_reconciliation_required"


def test_upload_id_in_non_complete_state_fails_closed_without_matching_tracking(
    tmp_path: Path, runner: ModuleType
) -> None:
    collection = _collection(tmp_path, phase="publishing", upload={"video_id": "already-uploaded"})

    decision = runner.evaluate_collection(tmp_path, collection, _config(runner, publish=True))

    assert decision["action"] == "blocked"
    assert decision["reason"] == "upload_state_inconsistent"


def test_complete_phase_still_reconciles_when_stage_is_not_live(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(tmp_path, phase="complete", upload={"video_id": "already-uploaded"})
    (collection / "20-documentation" / "upload_tracking.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "status": "completed",
                "complete_collection": {"status": "completed", "video_id": "already-uploaded"},
            }
        ),
        encoding="utf-8",
    )

    decision = runner.evaluate_collection(tmp_path, collection, _config(runner, publish=True))

    assert decision["action"] == "wf-next"
    assert decision["reason"] == "upload_reconciliation_required"


def test_lease_prevents_concurrent_run_and_recovers_after_expiry(tmp_path: Path, runner: ModuleType) -> None:
    first = runner.acquire_lease(tmp_path, now=100.0, ttl_seconds=60)
    assert runner.heartbeat_lease(tmp_path, first, now=120.0, ttl_seconds=60) is True

    with pytest.raises(runner.LeaseBusyError):
        runner.acquire_lease(tmp_path, now=161.0, ttl_seconds=60)

    recovered = runner.acquire_lease(tmp_path, now=181.0, ttl_seconds=60)
    assert recovered != first
    assert runner.heartbeat_lease(tmp_path, first, now=182.0, ttl_seconds=60) is False
    assert runner.release_lease(tmp_path, recovered) is True
    assert runner.release_lease(tmp_path, first) is False


def test_expired_owner_cannot_heartbeat_before_takeover(tmp_path: Path, runner: ModuleType) -> None:
    token = runner.acquire_lease(tmp_path, now=100.0, ttl_seconds=60)

    assert runner.heartbeat_lease(tmp_path, token, now=161.0, ttl_seconds=60) is False


def test_acquire_recovers_incomplete_lease_directory(tmp_path: Path, runner: ModuleType) -> None:
    orphan = tmp_path / ".automation-run" / "lease"
    orphan.mkdir(parents=True)

    token = runner.acquire_lease(tmp_path, now=100.0, ttl_seconds=60)

    assert runner.heartbeat_lease(tmp_path, token, now=101.0, ttl_seconds=60) is True


def test_state_directory_symlink_is_rejected(tmp_path: Path, runner: ModuleType) -> None:
    external = tmp_path / "external-state"
    external.mkdir()
    (tmp_path / ".automation-run").symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        runner.acquire_lease(tmp_path, now=100.0, ttl_seconds=60)


def test_history_records_failure_resume_point_without_mutating_workflow_state(
    tmp_path: Path, runner: ModuleType
) -> None:
    collection = _collection(tmp_path)
    state_before = (collection / "workflow-state.json").read_bytes()
    token = runner.acquire_lease(tmp_path, now=time.time(), ttl_seconds=60)

    runner.record_attempt(
        tmp_path,
        token=token,
        collection=collection,
        action="suno-helper",
        status="failed",
        reason="captcha-required",
        resume_action="suno-helper",
        now="2026-07-18T12:00:00+00:00",
    )

    history = json.loads((tmp_path / ".automation-run" / "history.json").read_text(encoding="utf-8"))
    assert history["attempts"][-1]["status"] == "failed"
    assert history["attempts"][-1]["resume_action"] == "suno-helper"
    assert history["attempts"][-1]["run_id"]
    assert "token" not in history["attempts"][-1]
    assert (collection / "workflow-state.json").read_bytes() == state_before

    with pytest.raises(runner.LeaseBusyError, match="token"):
        runner.record_attempt(
            tmp_path,
            token="not-owner",
            collection=collection,
            action="suno-helper",
            status="failed",
            reason="must-not-write",
            resume_action="suno-helper",
            now="2026-07-18T12:01:00+00:00",
        )

    with pytest.raises(ValueError, match="未知の action"):
        runner.record_attempt(
            tmp_path,
            token=token,
            collection=collection,
            action="invented-step",
            status="failed",
            reason="must-not-write",
            resume_action=None,
            now="2026-07-18T12:01:00+00:00",
        )


def test_skill_and_scheduler_delegate_to_integrated_runner() -> None:
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    scheduler = (ROOT / ".claude" / "skills" / "automation-schedule" / "SKILL.md").read_text(encoding="utf-8")
    workflow_model = (ROOT / "src" / "youtube_automation" / "utils" / "config" / "workflow.py").read_text(
        encoding="utf-8"
    )

    for child in ("wf-new", "lyria", "suno-helper", "masterup", "wf-next", "post-publish"):
        assert f"/{child}" in skill
    assert "allow_external_publish" in skill
    assert "--target-workflow automation-run" in scheduler
    assert 'target_workflow: str = "automation-run"' in workflow_model
