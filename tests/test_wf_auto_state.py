"""`/wf-auto` の新規開始・固定・再開契約テスト。"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / ".claude" / "skills" / "wf-auto"
SCRIPT = SKILL_DIR / "references" / "wf-auto-state.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("wf_auto_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runner() -> ModuleType:
    return _load_module()


def _config(runner: ModuleType, *, publish: bool = False, post_publish: bool = False):
    return runner.RunnerConfig(
        allow_external_publish=publish,
        post_publish_configured=post_publish,
    )


def _collection(
    root: Path,
    name: str,
    *,
    stage: str = "planning",
    phase: str = "prepared",
    engine: str = "lyria",
    assets: dict | None = None,
    upload: dict | None = None,
) -> Path:
    collection = root / "collections" / stage / name
    for directory in ("01-master", "02-Individual-music", "20-documentation"):
        (collection / directory).mkdir(parents=True, exist_ok=True)
    state = {
        "collection_name": name,
        "created_at": "2026-07-21T00:00:00+00:00",
        "stage": stage,
        "phase": phase,
        "music_engine": engine,
        "planning": {"music": {"engine": engine}},
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


def test_no_active_collection_starts_wf_new_without_fabricating_state(tmp_path: Path, runner: ModuleType) -> None:
    decision = runner.resolve_action(tmp_path, config=_config(runner))

    assert decision == {
        "collection": None,
        "phase": "absent",
        "engine": None,
        "action": "wf-new",
        "reason": "no_active_collection",
        "resume_action": "wf-new",
        "allow_external_publish": False,
    }
    assert not (tmp_path / "collections").exists()


def test_created_collection_is_pinned_before_replanning(tmp_path: Path, runner: ModuleType) -> None:
    _collection(tmp_path, "20260720-older")
    created = _collection(tmp_path, "20260721-created")

    decision = runner.resolve_action(tmp_path, created.name, config=_config(runner))

    assert decision["collection"] == created.as_posix()
    assert decision["action"] == "lyria"
    assert decision["reason"] == "lyria_generation_required"


def test_interactive_approval_replans_same_collection_in_same_run(tmp_path: Path, runner: ModuleType) -> None:
    _collection(tmp_path, "20260720-other")
    created = _collection(tmp_path, "20260721-created", phase="planning")

    before_approval = runner.resolve_action(tmp_path, created.name, config=_config(runner))
    state_path = created / "workflow-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["phase"] = "prepared"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    after_approval = runner.resolve_action(tmp_path, created.name, config=_config(runner))

    assert before_approval["action"] == "wf-new"
    assert before_approval["collection"] == created.as_posix()
    assert after_approval["action"] == "lyria"
    assert after_approval["collection"] == created.as_posix()


def test_existing_collection_resumes_from_verified_artifacts(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(
        tmp_path,
        "20260721-resume",
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

    decision = runner.resolve_action(tmp_path, config=_config(runner, publish=False))

    assert decision["action"] == "blocked"
    assert decision["reason"] == "external_publish_disabled"
    assert decision["resume_action"] == "wf-next"


def test_unattended_manual_intervention_is_recorded_with_resume_action(tmp_path: Path, runner: ModuleType) -> None:
    token = runner.acquire_lease(tmp_path, now=time.time(), ttl_seconds=60)

    runner.record_bootstrap_attempt(
        tmp_path,
        token=token,
        status="blocked",
        reason="user_input_required",
        now="2026-07-21T00:00:00+00:00",
    )

    history = json.loads((tmp_path / ".automation-run" / "history.json").read_text(encoding="utf-8"))
    assert history["attempts"][-1]["status"] == "blocked"
    assert history["attempts"][-1]["collection"] is None
    assert history["attempts"][-1]["action"] == "wf-new"
    assert history["attempts"][-1]["resume_action"] == "wf-new"


def test_completed_live_collection_finishes_after_post_publish_history(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(
        tmp_path,
        "20260721-complete",
        stage="live",
        phase="complete",
        upload={"video_id": "video-123", "video_url": "https://youtu.be/video-123"},
    )
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

    decision = runner.resolve_action(
        tmp_path,
        collection.name,
        config=_config(runner, publish=True, post_publish=True),
    )

    assert decision["action"] == "complete"


def test_cli_plan_prints_bootstrap_decision(
    tmp_path: Path, runner: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "_load_runner_config", lambda root: _config(runner))

    assert runner.main(["plan", "--channel-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["reason"] == "no_active_collection"


def test_cli_records_bootstrap_block_before_collection_exists(
    tmp_path: Path, runner: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    token = runner.acquire_lease(tmp_path, now=time.time(), ttl_seconds=60)

    assert (
        runner.main(
            [
                "record-bootstrap",
                "--channel-dir",
                str(tmp_path),
                "--token",
                token,
                "--status",
                "blocked",
                "--reason",
                "user_input_required",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {"status": "recorded"}
