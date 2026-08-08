"""`/wf-auto` の新規開始・固定・再開契約テスト。"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
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
    assert history["attempts"][-1]["timing"] is None


def test_schema_v1_history_reads_timing_as_unavailable_without_mutation(tmp_path: Path, runner: ModuleType) -> None:
    history_path = tmp_path / ".automation-run" / "history.json"
    history_path.parent.mkdir()
    original = {
        "schema_version": 1,
        "attempts": [
            {"action": "wf-new", "status": "failed", "recorded_at": "2026-07-21T00:00:00+00:00"},
            {"action": "wf-new", "status": "blocked", "recorded_at": "2026-07-21T00:01:00+00:00"},
        ],
    }
    history_path.write_text(json.dumps(original), encoding="utf-8")

    history = runner.read_history(tmp_path)

    assert [attempt["status"] for attempt in history["attempts"]] == ["failed", "blocked"]
    assert [attempt["timing"] for attempt in history["attempts"]] == [None, None]
    assert json.loads(history_path.read_text(encoding="utf-8")) == original


def test_schema_v2_appends_typed_segments_and_preserves_every_attempt(tmp_path: Path, runner: ModuleType) -> None:
    token = runner.acquire_lease(tmp_path, now=time.time(), ttl_seconds=60)
    history_path = tmp_path / ".automation-run" / "history.json"
    history_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "attempts": [{"action": "wf-new", "status": "failed", "recorded_at": "2026-07-20T23:59:00+00:00"}],
            }
        ),
        encoding="utf-8",
    )
    segments = [
        {
            "kind": "ai",
            "started_at": "2026-07-21T00:00:00+00:00",
            "ended_at": "2026-07-21T00:00:12+00:00",
            "duration_seconds": 12.0,
        },
        {
            "kind": "human",
            "started_at": "2026-07-21T00:00:12+00:00",
            "ended_at": "2026-07-21T00:00:17+00:00",
            "duration_seconds": 5.0,
        },
    ]

    for index, status in enumerate(("blocked", "failed", "success")):
        runner.record_attempt(
            tmp_path,
            token=token,
            collection=None,
            action="wf-new",
            status=status,
            reason=f"attempt_{status}",
            resume_action=None,
            now=f"2026-07-21T00:0{index}:17+00:00",
            segments=segments,
        )

    history = runner.read_history(tmp_path)
    assert history["schema_version"] == 2
    assert [attempt["status"] for attempt in history["attempts"]] == ["failed", "blocked", "failed", "success"]
    assert history["attempts"][0]["timing"] is None
    assert history["attempts"][-1]["timing"] == {
        "started_at": "2026-07-21T00:00:00+00:00",
        "ended_at": "2026-07-21T00:00:17+00:00",
        "ai_seconds": 12.0,
        "human_seconds": 5.0,
        "segments": segments,
    }


@pytest.mark.parametrize(
    ("segment", "message"),
    [
        (
            {"kind": "ai", "started_at": "2026-07-21T00:00:00+00:00", "duration_seconds": 1.0},
            "open segment",
        ),
        (
            {
                "kind": "ai",
                "started_at": "2026-07-21T00:00:01+00:00",
                "ended_at": "2026-07-21T00:00:00+00:00",
                "duration_seconds": 1.0,
            },
            "ended_at",
        ),
        (
            {
                "kind": "human",
                "started_at": "2026-07-21T00:00:00+00:00",
                "ended_at": "2026-07-21T00:00:01+00:00",
                "duration_seconds": -1.0,
            },
            "duration_seconds",
        ),
        (
            {
                "kind": "ai",
                "started_at": "2026-07-21T00:00:00+00:00",
                "ended_at": "2026-07-21T00:00:01+00:00",
                "duration_seconds": float("nan"),
            },
            "duration_seconds",
        ),
        (
            {
                "kind": "ai",
                "started_at": "2026-07-21T00:00:00+00:00",
                "ended_at": "2026-07-21T00:00:01+00:00",
                "duration_seconds": float("inf"),
            },
            "duration_seconds",
        ),
        (
            {
                "kind": "human",
                "started_at": "2026-07-21T00:00:00+00:00",
                "ended_at": "2026-07-21T00:00:01+00:00",
                "duration_seconds": float("-inf"),
            },
            "duration_seconds",
        ),
    ],
)
def test_invalid_timing_fails_loud_on_read_and_append_without_mutating_history(
    tmp_path: Path,
    runner: ModuleType,
    segment: dict,
    message: str,
) -> None:
    token = runner.acquire_lease(tmp_path, now=time.time(), ttl_seconds=60)
    history_path = tmp_path / ".automation-run" / "history.json"
    invalid_history = {
        "schema_version": 2,
        "attempts": [{"action": "wf-new", "status": "failed", "timing": {"segments": [segment]}}],
    }
    history_path.write_text(json.dumps(invalid_history), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        runner.read_history(tmp_path)

    original = json.dumps({"schema_version": 2, "attempts": []})
    history_path.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        runner.record_attempt(
            tmp_path,
            token=token,
            collection=None,
            action="wf-new",
            status="failed",
            reason="invalid_timing",
            resume_action="wf-new",
            now="2026-07-21T00:00:02+00:00",
            segments=[segment],
        )
    assert history_path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("status", ["success", "failed", "blocked"])
def test_cli_record_closes_ai_segment_for_every_outcome(
    tmp_path: Path,
    runner: ModuleType,
    status: str,
) -> None:
    collection = _collection(tmp_path, "20260721-timed")
    token = runner.acquire_lease(tmp_path, now=time.time(), ttl_seconds=60)
    started_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

    assert (
        runner.main(
            [
                "record",
                "--channel-dir",
                str(tmp_path),
                "--token",
                token,
                "--collection",
                collection.name,
                "--action",
                "lyria",
                "--status",
                status,
                "--reason",
                f"timed_{status}",
                "--ai-started-at",
                started_at,
            ]
        )
        == 0
    )

    attempt = runner.read_history(tmp_path)["attempts"][-1]
    assert attempt["status"] == status
    assert attempt["timing"]["human_seconds"] == 0
    assert attempt["timing"]["ai_seconds"] >= 1
    assert attempt["timing"]["segments"] == [
        {
            "kind": "ai",
            "started_at": started_at,
            "ended_at": attempt["timing"]["ended_at"],
            "duration_seconds": attempt["timing"]["ai_seconds"],
        }
    ]


def test_cli_record_retry_appends_new_timed_attempt_without_overwriting_failure(
    tmp_path: Path, runner: ModuleType
) -> None:
    collection = _collection(tmp_path, "20260721-retry")
    token = runner.acquire_lease(tmp_path, now=time.time(), ttl_seconds=60)

    for index, status in enumerate(("failed", "success"), start=1):
        started_at = (datetime.now(UTC) - timedelta(seconds=index)).isoformat()
        assert (
            runner.main(
                [
                    "record",
                    "--channel-dir",
                    str(tmp_path),
                    "--token",
                    token,
                    "--collection",
                    collection.name,
                    "--action",
                    "lyria",
                    "--status",
                    status,
                    "--reason",
                    f"attempt_{status}",
                    "--ai-started-at",
                    started_at,
                ]
            )
            == 0
        )

    attempts = runner.read_history(tmp_path)["attempts"]
    assert [attempt["status"] for attempt in attempts] == ["failed", "success"]
    assert all(attempt["timing"]["segments"][0]["kind"] == "ai" for attempt in attempts)


def test_cli_record_without_ai_start_keeps_timing_unavailable(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(tmp_path, "20260721-legacy-record")
    token = runner.acquire_lease(tmp_path, now=time.time(), ttl_seconds=60)

    assert (
        runner.main(
            [
                "record",
                "--channel-dir",
                str(tmp_path),
                "--token",
                token,
                "--collection",
                collection.name,
                "--action",
                "lyria",
                "--status",
                "success",
                "--reason",
                "legacy_caller",
            ]
        )
        == 0
    )

    assert runner.read_history(tmp_path)["attempts"][-1]["timing"] is None


def test_cli_record_splits_ai_timing_around_one_human_interval(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(tmp_path, "20260721-one-human-gate")
    token = runner.acquire_lease(tmp_path, now=time.time(), ttl_seconds=60)
    started = datetime.now(UTC) - timedelta(seconds=30)
    human_started = started + timedelta(seconds=10)
    human_ended = started + timedelta(seconds=15)

    assert (
        runner.main(
            [
                "record",
                "--channel-dir",
                str(tmp_path),
                "--token",
                token,
                "--collection",
                collection.name,
                "--action",
                "lyria",
                "--status",
                "success",
                "--reason",
                "approved",
                "--ai-started-at",
                started.isoformat(),
                "--human-interval",
                human_started.isoformat(),
                human_ended.isoformat(),
            ]
        )
        == 0
    )

    timing = runner.read_history(tmp_path)["attempts"][-1]["timing"]
    assert [segment["kind"] for segment in timing["segments"]] == ["ai", "human", "ai"]
    assert timing["segments"][0] == {
        "kind": "ai",
        "started_at": started.isoformat(),
        "ended_at": human_started.isoformat(),
        "duration_seconds": 10.0,
    }
    assert timing["segments"][1] == {
        "kind": "human",
        "started_at": human_started.isoformat(),
        "ended_at": human_ended.isoformat(),
        "duration_seconds": 5.0,
    }
    assert timing["segments"][2]["started_at"] == human_ended.isoformat()
    assert timing["segments"][2]["ended_at"] == timing["ended_at"]
    assert timing["human_seconds"] == 5.0
    assert timing["ai_seconds"] == pytest.approx(
        (datetime.fromisoformat(timing["ended_at"]) - started).total_seconds() - 5.0
    )


def test_human_intervals_build_continuous_typed_segments(runner: ModuleType) -> None:
    segments = runner._timing_segments(
        "2026-07-21T00:00:00+00:00",
        [
            ["2026-07-21T00:00:10+00:00", "2026-07-21T00:00:15+00:00"],
            ["2026-07-21T00:00:20+00:00", "2026-07-21T00:00:24+00:00"],
        ],
        "2026-07-21T00:00:30+00:00",
    )

    assert segments == [
        {
            "kind": "ai",
            "started_at": "2026-07-21T00:00:00+00:00",
            "ended_at": "2026-07-21T00:00:10+00:00",
            "duration_seconds": 10.0,
        },
        {
            "kind": "human",
            "started_at": "2026-07-21T00:00:10+00:00",
            "ended_at": "2026-07-21T00:00:15+00:00",
            "duration_seconds": 5.0,
        },
        {
            "kind": "ai",
            "started_at": "2026-07-21T00:00:15+00:00",
            "ended_at": "2026-07-21T00:00:20+00:00",
            "duration_seconds": 5.0,
        },
        {
            "kind": "human",
            "started_at": "2026-07-21T00:00:20+00:00",
            "ended_at": "2026-07-21T00:00:24+00:00",
            "duration_seconds": 4.0,
        },
        {
            "kind": "ai",
            "started_at": "2026-07-21T00:00:24+00:00",
            "ended_at": "2026-07-21T00:00:30+00:00",
            "duration_seconds": 6.0,
        },
    ]


@pytest.mark.parametrize(
    ("ai_started_at", "human_intervals", "message"),
    [
        (None, [["2026-07-21T00:00:01+00:00", "2026-07-21T00:00:02+00:00"]], "ai_started_at"),
        (
            "2026-07-21T00:00:00+00:00",
            [["2026-07-21T00:00:02+00:00", "2026-07-21T00:00:01+00:00"]],
            "ended_at",
        ),
        (
            "2026-07-21T00:00:00+00:00",
            [
                ["2026-07-21T00:00:01+00:00", "2026-07-21T00:00:03+00:00"],
                ["2026-07-21T00:00:02+00:00", "2026-07-21T00:00:04+00:00"],
            ],
            "overlap",
        ),
        (
            "2026-07-21T00:00:00+00:00",
            [["2026-07-20T23:59:59+00:00", "2026-07-21T00:00:01+00:00"]],
            "ai_started_at",
        ),
        (
            "2026-07-21T00:00:00+00:00",
            [["2099-07-21T00:00:01+00:00", "2099-07-21T00:00:02+00:00"]],
            "recorded_at",
        ),
        (
            "2026-07-21T00:00:00+00:00",
            [["2026-07-21T00:00:01", "2026-07-21T00:00:02"]],
            "timezone",
        ),
    ],
)
def test_cli_record_rejects_invalid_human_intervals_without_mutating_history(
    tmp_path: Path,
    runner: ModuleType,
    capsys: pytest.CaptureFixture[str],
    ai_started_at: str | None,
    human_intervals: list[list[str]],
    message: str,
) -> None:
    collection = _collection(tmp_path, "20260721-invalid-human-gate")
    token = runner.acquire_lease(tmp_path, now=time.time(), ttl_seconds=60)
    history_path = tmp_path / ".automation-run" / "history.json"
    original = json.dumps({"schema_version": 2, "attempts": []})
    history_path.write_text(original, encoding="utf-8")
    argv = [
        "record",
        "--channel-dir",
        str(tmp_path),
        "--token",
        token,
        "--collection",
        collection.name,
        "--action",
        "lyria",
        "--status",
        "failed",
        "--reason",
        "invalid_gate",
    ]
    if ai_started_at is not None:
        argv.extend(["--ai-started-at", ai_started_at])
    for interval in human_intervals:
        argv.extend(["--human-interval", *interval])

    assert runner.main(argv) == 2

    assert message in json.loads(capsys.readouterr().out)["reason"]
    assert history_path.read_text(encoding="utf-8") == original


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


@pytest.mark.parametrize("status", ["blocked", "failed"])
def test_cli_records_timed_bootstrap_stop_before_collection_exists(
    tmp_path: Path,
    runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
) -> None:
    safe_token = "a1" * 24
    monkeypatch.setattr(runner.secrets, "token_urlsafe", lambda _: "-unsafe-token")
    monkeypatch.setattr(runner.secrets, "token_hex", lambda _: safe_token)

    token = runner.acquire_lease(tmp_path, now=time.time(), ttl_seconds=60)
    started_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

    assert token == safe_token
    assert (
        runner.main(
            [
                "record-bootstrap",
                "--channel-dir",
                str(tmp_path),
                "--token",
                token,
                "--status",
                status,
                "--reason",
                "user_input_required",
                "--ai-started-at",
                started_at,
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {"status": "recorded"}
    attempt = runner.read_history(tmp_path)["attempts"][-1]
    assert attempt["collection"] is None
    assert attempt["action"] == "wf-new"
    assert attempt["status"] == status
    assert attempt["timing"]["segments"] == [
        {
            "kind": "ai",
            "started_at": started_at,
            "ended_at": attempt["timing"]["ended_at"],
            "duration_seconds": attempt["timing"]["ai_seconds"],
        }
    ]
