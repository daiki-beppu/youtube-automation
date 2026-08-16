"""Git workflow state から作る dashboard pipeline read model。"""

from __future__ import annotations

import json
from pathlib import Path

from youtube_automation.infrastructure.analytics.dashboard_read_model import (
    DashboardAPI,
    build_dashboard_read_model,
)


def _channel(root: Path, name: str) -> Path:
    meta = root / "config" / "channel" / "meta.json"
    meta.parent.mkdir(parents=True)
    meta.write_text(json.dumps({"channel": {"name": name}}), encoding="utf-8")
    return root


def _state(
    channel: Path,
    collection: str,
    *,
    stage: str,
    phase: str,
    engine: str,
    updated_at: str,
    handoff: dict[str, str] | None = None,
) -> None:
    path = channel / "collections" / stage / collection / "workflow-state.json"
    path.parent.mkdir(parents=True)
    payload: dict[str, object] = {
        "collection_name": collection,
        "stage": stage,
        "phase": phase,
        "updated_at": updated_at,
        "planning": {"music": {"engine": engine}},
    }
    if handoff is not None:
        payload["handoff"] = handoff
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_pipeline_lists_every_channel_and_projects_canonical_state(tmp_path: Path) -> None:
    active = _channel(tmp_path / "active", "Active Channel")
    empty = _channel(tmp_path / "empty", "Empty Channel")
    _state(
        active,
        "local-suno",
        stage="planning",
        phase="prepared",
        engine="suno",
        updated_at="2026-08-16T09:00:00+00:00",
    )
    _state(
        active,
        "cloud-suno",
        stage="planning",
        phase="cloud_owned",
        engine="suno",
        updated_at="2026-08-16T10:00:00+00:00",
        handoff={
            "point": "suno_download",
            "owner": "cloud",
            "manifest_key": "active/cloud-suno/suno-download/manifest.json",
            "root_sha256": "a" * 64,
        },
    )
    _state(
        active,
        "cloud-lyria",
        stage="live",
        phase="complete",
        engine="lyria",
        updated_at="2026-08-16T11:00:00+00:00",
    )

    pipeline = DashboardAPI(build_dashboard_read_model([active, empty])).pipeline()

    assert [channel["name"] for channel in pipeline["channels"]] == ["Active Channel", "Empty Channel"]
    assert pipeline["channels"][1]["collections"] == []
    assert pipeline["channels"][1]["error"] is None
    collections = pipeline["channels"][0]["collections"]
    assert collections == [
        {
            "collection_id": "cloud-suno",
            "stage": "planning",
            "phase": "cloud_owned",
            "execution_owner": "cloud",
            "handoff_status": "completed",
            "latest_event": {
                "kind": "workflow_state_updated",
                "occurred_at": "2026-08-16T10:00:00+00:00",
            },
            "error": None,
        },
        {
            "collection_id": "local-suno",
            "stage": "planning",
            "phase": "prepared",
            "execution_owner": "local",
            "handoff_status": "pending",
            "latest_event": {
                "kind": "workflow_state_updated",
                "occurred_at": "2026-08-16T09:00:00+00:00",
            },
            "error": None,
        },
        {
            "collection_id": "cloud-lyria",
            "stage": "live",
            "phase": "complete",
            "execution_owner": "cloud",
            "handoff_status": "not_applicable",
            "latest_event": {
                "kind": "workflow_state_updated",
                "occurred_at": "2026-08-16T11:00:00+00:00",
            },
            "error": None,
        },
    ]


def test_pipeline_keeps_invalid_collection_visible_with_actionable_error(tmp_path: Path) -> None:
    channel = _channel(tmp_path / "invalid", "Invalid State")
    state = channel / "collections" / "planning" / "broken" / "workflow-state.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"phase":"unknown"}', encoding="utf-8")

    collection = DashboardAPI(build_dashboard_read_model([channel])).pipeline()["channels"][0]["collections"][0]

    assert collection["collection_id"] == "broken"
    assert collection["phase"] is None
    assert collection["execution_owner"] is None
    assert collection["handoff_status"] == "invalid"
    assert collection["latest_event"] is None
    assert collection["error"] is not None
    assert collection["error"]["code"] == "workflow_state_invalid"


def test_pipeline_isolates_symlinked_collection_root(tmp_path: Path) -> None:
    channel = _channel(tmp_path / "channel", "Unsafe Channel")
    outside = tmp_path / "outside"
    outside.mkdir()
    (channel / "collections").symlink_to(outside, target_is_directory=True)

    pipeline_channel = DashboardAPI(build_dashboard_read_model([channel])).pipeline()["channels"][0]

    assert pipeline_channel["collections"] == []
    assert pipeline_channel["error"] is not None
    assert pipeline_channel["error"]["code"] == "workflow_state_discovery_failed"
