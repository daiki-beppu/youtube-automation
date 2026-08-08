from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.infrastructure.analytics.workflow_timing import build_workflow_timing


def _write_collection(channel: Path, stage: str, name: str, *, phase: str, created_at: str) -> Path:
    collection = channel / "collections" / stage / name
    collection.mkdir(parents=True)
    (collection / "workflow-state.json").write_text(
        json.dumps({"phase": phase, "created_at": created_at}),
        encoding="utf-8",
    )
    return collection


def _attempt(collection: str, action: str, status: str, ai: float, human: float) -> dict[str, object]:
    return {
        "collection": collection,
        "action": action,
        "status": status,
        "timing": {
            "segments": [
                {
                    "kind": "ai",
                    "started_at": "2026-08-01T00:00:00+00:00",
                    "ended_at": "2026-08-01T00:00:10+00:00",
                    "duration_seconds": ai,
                },
                {
                    "kind": "human",
                    "started_at": "2026-08-01T00:00:10+00:00",
                    "ended_at": "2026-08-01T00:00:20+00:00",
                    "duration_seconds": human,
                },
            ]
        },
    }


def _write_history(channel: Path, attempts: list[dict[str, object]]) -> None:
    state = channel / ".automation-run"
    state.mkdir()
    (state / "history.json").write_text(
        json.dumps({"schema_version": 2, "attempts": attempts}),
        encoding="utf-8",
    )


def _write_active_lease(channel: Path) -> None:
    lease = channel / ".automation-run" / "lease"
    lease.mkdir(parents=True, exist_ok=True)
    (lease / "lease.json").write_text(
        json.dumps({"token": "active", "acquired_at": 0, "expires_at": 4_102_444_800}),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("planning", "live", "expected"),
    [
        (True, False, [("active", "planning")]),
        (False, True, [("latest", "live")]),
        (True, True, [("active", "planning"), ("latest", "live")]),
        (False, False, []),
    ],
)
def test_build_workflow_timing_selects_active_and_latest_collections(
    tmp_path: Path,
    planning: bool,
    live: bool,
    expected: list[tuple[str, str]],
) -> None:
    if planning:
        _write_collection(tmp_path, "planning", "active", phase="planning", created_at="2026-08-02")
    if live:
        _write_collection(tmp_path, "live", "latest", phase="complete", created_at="2026-08-01")
    attempts = []
    if planning:
        attempts.append(_attempt("collections/planning/active", "wf-next", "success", 1, 1))
    if live:
        attempts.append(_attempt("collections/live/latest", "post-publish", "success", 1, 1))
    _write_history(tmp_path, attempts)

    result = build_workflow_timing(tmp_path, {"wf-next": 1.0, "post-publish": 1.0})

    assert result["status"] == "ready"
    assert [(item["collection_id"], item["stage"]) for item in result["collections"]] == expected


def test_build_workflow_timing_returns_canonical_step_and_total_metrics(tmp_path: Path) -> None:
    _write_collection(tmp_path, "planning", "active", phase="planning", created_at="2026-08-02")
    _write_collection(tmp_path, "live", "older", phase="complete", created_at="2026-07-01")
    _write_collection(tmp_path, "live", "latest", phase="complete", created_at="2026-08-01")
    _write_history(
        tmp_path,
        [
            _attempt("collections/planning/active", "wf-next", "failed", 10, 5),
            _attempt("collections/planning/active", "wf-next", "success", 20, 10),
            _attempt("collections/live/latest", "post-publish", "success", 15, 5),
            _attempt("collections/live/older", "post-publish", "success", 99, 99),
        ],
    )

    result = build_workflow_timing(tmp_path, {"wf-next": 1.0, "post-publish": 2.0})

    assert result["status"] == "ready"
    active, latest = result["collections"]
    assert active["steps"] == [
        {
            "action": "wf-next",
            "status": "success",
            "manual_baseline_seconds": 60.0,
            "ai_seconds": 30.0,
            "human_seconds": 15.0,
            "work_seconds": 45.0,
            "ai_inclusive_saved_seconds": 15.0,
            "human_freed_seconds": 45.0,
        }
    ]
    assert active["totals"] == {
        "manual_baseline_seconds": 60.0,
        "ai_seconds": 30.0,
        "human_seconds": 15.0,
        "work_seconds": 45.0,
        "ai_inclusive_saved_seconds": 15.0,
        "human_freed_seconds": 45.0,
    }
    assert latest["collection_id"] == "latest"
    assert latest["steps"][0]["action"] == "post-publish"
    assert latest["totals"]["work_seconds"] == 20.0


@pytest.mark.parametrize(
    ("history", "baseline", "reason"),
    [
        ({"schema_version": 1, "attempts": []}, {"wf-next": 1.0}, "history_schema_v1"),
        ({"schema_version": 2, "attempts": []}, None, "manual_baseline_unconfigured"),
        ({"schema_version": 2, "attempts": []}, {}, "attempt_timing_unavailable"),
        (
            {
                "schema_version": 2,
                "attempts": [
                    {
                        "collection": "collections/planning/active",
                        "action": "wf-next",
                        "status": "success",
                        "timing": None,
                    }
                ],
            },
            {"wf-next": 1.0},
            "attempt_timing_unavailable",
        ),
    ],
)
def test_build_workflow_timing_exposes_unavailable_without_zero_metrics(
    tmp_path: Path,
    history: dict[str, object],
    baseline: dict[str, float] | None,
    reason: str,
) -> None:
    _write_collection(tmp_path, "planning", "active", phase="planning", created_at="2026-08-02")
    state = tmp_path / ".automation-run"
    state.mkdir()
    (state / "history.json").write_text(json.dumps(history), encoding="utf-8")

    result = build_workflow_timing(tmp_path, baseline)

    assert result == {"status": "unavailable", "reason": reason, "collections": []}


def test_build_workflow_timing_exposes_active_lease_as_in_progress(tmp_path: Path) -> None:
    _write_collection(tmp_path, "planning", "active", phase="planning", created_at="2026-08-02")
    _write_history(
        tmp_path,
        [_attempt("collections/planning/active", "wf-next", "success", 10, 5)],
    )
    _write_active_lease(tmp_path)

    result = build_workflow_timing(tmp_path, {"wf-next": 1.0})

    assert result["status"] == "in_progress"
    assert result["collections"][0]["totals"]["work_seconds"] == 15.0


def test_build_workflow_timing_keeps_in_progress_distinct_before_first_measurement(tmp_path: Path) -> None:
    _write_collection(tmp_path, "planning", "active", phase="planning", created_at="2026-08-02")
    _write_history(tmp_path, [])
    _write_active_lease(tmp_path)

    result = build_workflow_timing(tmp_path, None)

    assert result == {"status": "in_progress", "collections": []}
