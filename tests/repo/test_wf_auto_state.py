"""`/wf-new --auto` の新規開始・固定・再開契約テスト。"""

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
from tests.helpers.video_description import write_video_description_pair

ROOT = REPO_ROOT
SKILL_DIR = ROOT / ".claude" / "skills" / "wf-new"
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


def test_minimax_collection_routes_to_music_generate_without_suno_fallback(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(tmp_path, "20260721-minimax", engine="minimax")

    decision = runner.resolve_action(tmp_path, collection.name, config=_config(runner))

    assert decision["action"] == "minimax"
    assert decision["reason"] == "minimax_generation_required"
    assert decision["resume_action"] == "minimax"


def test_cloud_executor_is_noop_before_handoff_without_mutating_state(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(tmp_path, "20260721-local-owned", engine="suno")
    state_path = collection / "workflow-state.json"
    before = state_path.read_bytes()

    decision = runner.resolve_action(
        tmp_path,
        collection.name,
        config=_config(runner),
        executor="cloud",
    )

    assert decision["action"] == "no-op"
    assert decision["reason"] == "local_ownership"
    assert decision["resume_action"] is None
    assert state_path.read_bytes() == before


def test_cloud_executor_resumes_suno_after_manifest_handoff(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(
        tmp_path,
        "20260721-cloud-owned",
        phase="cloud_owned",
        engine="suno",
        assets={"music_downloaded": True},
    )
    state_path = collection / "workflow-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["planning"]["music"].update(
        {
            "expected_file_count": 2,
            "suno_playlist_url": "https://suno.com/playlist/example",
        }
    )
    state["handoff"] = {
        "point": "suno_download",
        "owner": "cloud",
        "manifest_key": "002ch/sample/suno-download/manifest.json",
        "root_sha256": "e" * 64,
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    (collection / "20-documentation" / "suno-prompts.json").write_text(
        json.dumps({"entries": [{"prompt": "one"}]}),
        encoding="utf-8",
    )
    (collection / "02-Individual-music" / "one.mp3").write_bytes(b"one")
    (collection / "02-Individual-music" / "two.mp3").write_bytes(b"two")

    cloud = runner.resolve_action(
        tmp_path,
        collection.name,
        config=_config(runner),
        executor="cloud",
    )
    local = runner.resolve_action(
        tmp_path,
        collection.name,
        config=_config(runner),
        executor="local",
    )

    assert cloud["phase"] == "cloud_owned"
    assert cloud["action"] == "masterup"
    assert cloud["reason"] == "suno_download_complete"
    assert local["action"] == "no-op"
    assert local["reason"] == "cloud_ownership"


def test_legacy_music_engine_only_state_remains_routable(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(tmp_path, "20260721-legacy", engine="lyria")
    state_path = collection / "workflow-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["music_engine"] = state["planning"]["music"].pop("engine")
    state_path.write_text(json.dumps(state), encoding="utf-8")

    decision = runner.resolve_action(tmp_path, collection.name, config=_config(runner))

    assert decision["action"] == "lyria"


def test_conflicting_music_engine_state_fails_before_action_selection(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(tmp_path, "20260721-conflict", engine="lyria")
    state_path = collection / "workflow-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["music_engine"] = "suno"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(ValueError, match="music engine mismatch"):
        runner.resolve_action(tmp_path, collection.name, config=_config(runner))


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
    write_video_description_pair(collection / "20-documentation")

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


def test_attempt_duration_summary_includes_every_status_and_work_item(runner: ModuleType) -> None:
    def attempt(collection: str, action: str, status: str, ai_seconds: float, human_seconds: float) -> dict:
        return {
            "collection": collection,
            "action": action,
            "status": status,
            "timing": {
                "segments": [
                    {
                        "kind": "ai",
                        "started_at": "2026-07-21T00:00:00+00:00",
                        "ended_at": "2026-07-21T00:00:01+00:00",
                        "duration_seconds": ai_seconds,
                    },
                    {
                        "kind": "human",
                        "started_at": "2026-07-21T00:00:01+00:00",
                        "ended_at": "2026-07-21T00:00:02+00:00",
                        "duration_seconds": human_seconds,
                    },
                ]
            },
        }

    history = {
        "schema_version": 2,
        "attempts": [
            attempt("collections/planning/a", "wf-next", "failed", 10.0, 2.0),
            attempt("collections/planning/a", "wf-next", "blocked", 5.0, 3.0),
            attempt("collections/planning/a", "wf-next", "success", 20.0, 1.0),
            attempt("collections/planning/b", "wf-next", "success", 30.0, 4.0),
            attempt("collections/planning/a", "masterup", "success", 7.0, 6.0),
        ],
    }

    summary = runner.summarize_attempt_durations(history)

    assert summary == {
        "available": True,
        "reason": None,
        "actions": {
            "masterup": {
                "ai_seconds": 7.0,
                "human_seconds": 6.0,
                "attempt_count": 1,
                "work_item_count": 1,
            },
            "wf-next": {
                "ai_seconds": 65.0,
                "human_seconds": 10.0,
                "attempt_count": 4,
                "work_item_count": 2,
            },
        },
        "totals": {
            "ai_seconds": 72.0,
            "human_seconds": 16.0,
            "attempt_count": 5,
            "work_item_count": 3,
        },
    }


@pytest.mark.parametrize(
    ("history", "reason"),
    [
        ({"schema_version": 1, "attempts": []}, "history_schema_v1"),
        (
            {"schema_version": 2, "attempts": [{"collection": None, "action": "wf-new", "timing": None}]},
            "attempt_timing_unavailable",
        ),
    ],
)
def test_attempt_duration_summary_distinguishes_unavailable_from_zero(
    runner: ModuleType, history: dict, reason: str
) -> None:
    assert runner.summarize_attempt_durations(history) == {
        "available": False,
        "reason": reason,
        "actions": None,
        "totals": None,
    }

    zero_summary = runner.summarize_attempt_durations(
        {
            "schema_version": 2,
            "attempts": [
                {
                    "collection": None,
                    "action": "wf-new",
                    "timing": {
                        "segments": [
                            {
                                "kind": "ai",
                                "started_at": "2026-07-21T00:00:00+00:00",
                                "ended_at": "2026-07-21T00:00:00+00:00",
                                "duration_seconds": 0.0,
                            }
                        ]
                    },
                }
            ],
        }
    )
    assert zero_summary["available"] is True
    assert zero_summary["totals"]["ai_seconds"] == 0.0


def test_time_savings_uses_every_attempt_and_baseline_per_work_item(runner: ModuleType) -> None:
    def attempt(collection: str, action: str, kind: str, duration: float) -> dict:
        return {
            "collection": collection,
            "action": action,
            "timing": {
                "segments": [
                    {
                        "kind": kind,
                        "started_at": "2026-07-21T00:00:00+00:00",
                        "ended_at": "2026-07-21T00:00:01+00:00",
                        "duration_seconds": duration,
                    }
                ]
            },
        }

    history = {
        "schema_version": 2,
        "attempts": [
            attempt("collections/planning/a", "wf-next", "ai", 50.0),
            attempt("collections/planning/a", "wf-next", "human", 30.0),
            attempt("collections/planning/b", "wf-next", "ai", 30.0),
            attempt("collections/planning/b", "wf-next", "human", 20.0),
            attempt("collections/planning/a", "masterup", "ai", 10.0),
            attempt("collections/planning/a", "masterup", "human", 20.0),
        ],
    }

    summary = runner.summarize_time_savings(history, {"wf-next": 1.0, "masterup": 1.0})

    assert summary["available"] is True
    assert summary["actions"]["wf-next"] == {
        "ai_seconds": 80.0,
        "human_seconds": 50.0,
        "attempt_count": 4,
        "work_item_count": 2,
        "manual_baseline_seconds": 120.0,
        "ai_inclusive_saved_seconds": 0.0,
        "human_freed_seconds": 70.0,
    }
    assert summary["actions"]["masterup"]["ai_inclusive_saved_seconds"] == 30.0
    assert summary["totals"] == {
        "ai_seconds": 90.0,
        "human_seconds": 70.0,
        "attempt_count": 6,
        "work_item_count": 3,
        "manual_baseline_seconds": 180.0,
        "ai_inclusive_saved_seconds": 20.0,
        "human_freed_seconds": 110.0,
    }


@pytest.mark.parametrize(
    ("history", "baselines", "reason"),
    [
        ({"schema_version": 2, "attempts": []}, None, "manual_baseline_unconfigured"),
        (
            {
                "schema_version": 2,
                "attempts": [
                    {
                        "collection": None,
                        "action": "wf-new",
                        "timing": {"segments": []},
                    }
                ],
            },
            {},
            "manual_baseline_missing:wf-new",
        ),
        ({"schema_version": 1, "attempts": []}, {"wf-new": 30.0}, "history_schema_v1"),
    ],
)
def test_time_savings_keeps_unavailable_distinct_from_zero(
    runner: ModuleType, history: dict, baselines: dict | None, reason: str
) -> None:
    assert runner.summarize_time_savings(history, baselines) == {
        "available": False,
        "reason": reason,
        "actions": None,
        "totals": None,
    }


def test_time_savings_clamps_negative_values_to_available_zero(runner: ModuleType) -> None:
    history = {
        "schema_version": 2,
        "attempts": [
            {
                "collection": "collections/planning/a",
                "action": "wf-next",
                "timing": {
                    "segments": [
                        {
                            "kind": "ai",
                            "started_at": "2026-07-21T00:00:00+00:00",
                            "ended_at": "2026-07-21T00:00:01+00:00",
                            "duration_seconds": 120.0,
                        },
                        {
                            "kind": "human",
                            "started_at": "2026-07-21T00:00:01+00:00",
                            "ended_at": "2026-07-21T00:00:02+00:00",
                            "duration_seconds": 60.0,
                        },
                    ]
                },
            }
        ],
    }

    summary = runner.summarize_time_savings(history, {"wf-next": 1.0})

    assert summary["available"] is True
    assert summary["totals"]["ai_inclusive_saved_seconds"] == 0.0
    assert summary["totals"]["human_freed_seconds"] == 0.0


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


def test_completed_live_collection_finishes_after_publish_artifacts(tmp_path: Path, runner: ModuleType) -> None:
    collection = _collection(
        tmp_path,
        "20260721-complete",
        stage="live",
        phase="complete",
        upload={"video_id": "video-123", "video_url": "https://youtu.be/video-123"},
    )
    (collection / "20-documentation" / "community-post.txt").write_text("published", encoding="utf-8")
    config_dir = tmp_path / "config" / "channel"
    config_dir.mkdir(parents=True)
    (config_dir / "pinned-comment.json").write_text(
        json.dumps({"pinned_comment": {"history_file": "pinned_comment_history.json"}}), encoding="utf-8"
    )
    (tmp_path / "pinned_comment_history.json").write_text(
        json.dumps({"schema_version": 1, "posted": {"video-123": {"posted_at": "done"}}}), encoding="utf-8"
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
    started_at = datetime.now(UTC) - timedelta(seconds=30)
    first_human_start = started_at + timedelta(seconds=5)
    first_human_end = started_at + timedelta(seconds=10)
    second_human_start = started_at + timedelta(seconds=15)
    second_human_end = started_at + timedelta(seconds=20)

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
                started_at.isoformat(),
                "--human-interval",
                first_human_start.isoformat(),
                first_human_end.isoformat(),
                "--human-interval",
                second_human_start.isoformat(),
                second_human_end.isoformat(),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {"status": "recorded"}
    attempt = runner.read_history(tmp_path)["attempts"][-1]
    assert attempt["collection"] is None
    assert attempt["action"] == "wf-new"
    assert attempt["status"] == status
    assert [segment["kind"] for segment in attempt["timing"]["segments"]] == [
        "ai",
        "human",
        "ai",
        "human",
        "ai",
    ]
    assert attempt["timing"]["segments"][1] == {
        "kind": "human",
        "started_at": first_human_start.isoformat(),
        "ended_at": first_human_end.isoformat(),
        "duration_seconds": 5.0,
    }
    assert attempt["timing"]["segments"][3] == {
        "kind": "human",
        "started_at": second_human_start.isoformat(),
        "ended_at": second_human_end.isoformat(),
        "duration_seconds": 5.0,
    }
    assert attempt["timing"]["human_seconds"] == 10.0


@pytest.mark.parametrize(
    ("ai_started_at", "human_intervals", "message"),
    [
        (None, [["2026-08-08T00:00:01+00:00", "2026-08-08T00:00:02+00:00"]], "ai_started_at"),
        (
            "2026-08-08T00:00:00+00:00",
            [
                ["2026-08-08T00:00:01+00:00", "2026-08-08T00:00:03+00:00"],
                ["2026-08-08T00:00:02+00:00", "2026-08-08T00:00:04+00:00"],
            ],
            "overlap",
        ),
    ],
)
def test_cli_rejects_invalid_bootstrap_human_intervals_without_mutating_history(
    tmp_path: Path,
    runner: ModuleType,
    capsys: pytest.CaptureFixture[str],
    ai_started_at: str | None,
    human_intervals: list[list[str]],
    message: str,
) -> None:
    token = runner.acquire_lease(tmp_path, now=time.time(), ttl_seconds=60)
    history_path = tmp_path / ".automation-run" / "history.json"
    original = json.dumps({"schema_version": 2, "attempts": []})
    history_path.write_text(original, encoding="utf-8")

    argv = [
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
    if ai_started_at is not None:
        argv.extend(["--ai-started-at", ai_started_at])
    for interval in human_intervals:
        argv.extend(["--human-interval", *interval])

    assert runner.main(argv) == 2
    assert message in json.loads(capsys.readouterr().out)["reason"]
    assert history_path.read_text(encoding="utf-8") == original
