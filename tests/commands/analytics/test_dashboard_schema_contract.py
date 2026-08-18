"""Python と dashboard TypeScript が共有する overview 応答契約。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.analytics.dashboard import create_server
from youtube_automation.infrastructure.analytics.dashboard_read_model import (
    SCHEMA_VERSION,
    ChannelOverviewResponse,
    ErrorResponse,
    OverviewResponse,
    PeriodResponse,
    PipelineResponse,
    SummaryResponse,
    TrendChannelResponse,
    TrendPointResponse,
    TrendsResponse,
)

GOLDEN_PATH = REPO_ROOT / "dashboard" / "src" / "lib" / "__fixtures__" / "overview.golden.json"
PIPELINE_GOLDEN_PATH = REPO_ROOT / "dashboard" / "src" / "lib" / "__fixtures__" / "pipeline.golden.json"
TRENDS_GOLDEN_PATH = REPO_ROOT / "dashboard" / "src" / "lib" / "__fixtures__" / "trends.golden.json"
UPDATE_ENV = "UPDATE_DASHBOARD_SCHEMA_GOLDEN"
REGEN_COMMAND = f"{UPDATE_ENV}=1 uv run pytest tests/commands/analytics/test_dashboard_schema_contract.py -q"


def _write_ready_channel(channel: Path) -> None:
    meta = channel / "config" / "channel" / "meta.json"
    meta.parent.mkdir(parents=True)
    meta.write_text(json.dumps({"channel": {"name": "Contract Ready"}}), encoding="utf-8")
    data = channel / "data"
    data.mkdir()
    (data / "analytics_data_20260812.json").write_text(
        json.dumps(
            {
                "collection_period": {
                    "start_date": "2026-08-01",
                    "end_date": "2026-08-12",
                    "collected_at": "2026-08-12T00:00:00+00:00",
                },
                "channel_analytics": {
                    "daily_metrics": [
                        {
                            "date": "2026-08-12",
                            "views": 120,
                            "watch_time": 90,
                            "subscribers_gained": 5,
                            "subscribers_lost": 2,
                        }
                    ],
                    "summary": {
                        "total_views": 1200,
                        "total_watch_time": 420,
                        "net_subscribers": 8,
                        "total_engagement": 31,
                        "avg_view_percentage": 62.5,
                    },
                },
                "scheduled_videos": {"count": 2},
                "video_analytics": {"video-1": {"title": "Contract Video", "views": 900}},
                "reporting_api": {"impressions_summary": {"per_day": [{"date": "2026-08-13", "impressions": 2400}]}},
            }
        ),
        encoding="utf-8",
    )
    state = channel / "collections" / "planning" / "contract-collection" / "workflow-state.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "collection_name": "contract-collection",
                "stage": "planning",
                "phase": "cloud_owned",
                "updated_at": "2026-08-12T01:00:00+00:00",
                "planning": {"music": {"engine": "suno"}},
                "handoff": {
                    "point": "suno_download",
                    "owner": "cloud",
                    "manifest_key": "ready/contract-collection/suno-download/manifest.json",
                    "root_sha256": "a" * 64,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_invalid_channel(channel: Path) -> None:
    meta = channel / "config" / "channel" / "meta.json"
    meta.parent.mkdir(parents=True)
    meta.write_text("not-json", encoding="utf-8")


def _contract_payload(tmp_path: Path) -> OverviewResponse:
    ready = tmp_path / "ready"
    invalid = tmp_path / "invalid"
    _write_ready_channel(ready)
    _write_invalid_channel(invalid)
    server = create_server(
        port=0,
        channel_paths=[ready, invalid],
        refresh_errors={ready: "refresh failed"},
    )
    try:
        overview = server.api.overview()
    finally:
        server.server_close()
    assert set(overview) == OverviewResponse.__required_keys__
    assert overview["schema_version"] == SCHEMA_VERSION

    channels = overview["channels"]
    assert all(set(channel) == ChannelOverviewResponse.__required_keys__ for channel in channels)
    ready_channel, invalid_channel = channels
    assert ready_channel["summary"] is not None
    assert set(ready_channel["summary"]) == SummaryResponse.__required_keys__
    assert set(ready_channel["period"]) == PeriodResponse.__required_keys__
    assert ready_channel["refresh_error"] is not None
    assert set(ready_channel["refresh_error"]) == ErrorResponse.__required_keys__
    assert invalid_channel["error"] is not None
    assert set(invalid_channel["error"]) == ErrorResponse.__required_keys__

    ready_channel["id"] = "channel-ready"
    invalid_channel["id"] = "channel-invalid"
    return overview


def _assert_golden_matches(generated: str, committed: str) -> None:
    assert generated == committed, (
        f"dashboard overview schema drifted from {GOLDEN_PATH.relative_to(REPO_ROOT)}. "
        f"Review the Python/TypeScript contract, then regenerate with: {REGEN_COMMAND}"
    )


def test_python_overview_matches_dashboard_golden(tmp_path: Path) -> None:
    generated = json.dumps(_contract_payload(tmp_path), ensure_ascii=False, indent=2) + "\n"
    if os.environ.get(UPDATE_ENV) == "1":
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(generated, encoding="utf-8")
    if not GOLDEN_PATH.exists():
        pytest.fail(f"dashboard overview golden is missing. Generate it with: {REGEN_COMMAND}")

    committed = GOLDEN_PATH.read_text(encoding="utf-8")

    _assert_golden_matches(generated, committed)


def test_python_pipeline_matches_dashboard_golden(tmp_path: Path) -> None:
    channel = tmp_path / "ready"
    _write_ready_channel(channel)
    server = create_server(port=0, channel_paths=[channel])
    try:
        pipeline: PipelineResponse = server.api.pipeline()
    finally:
        server.server_close()
    pipeline["channels"][0]["id"] = "channel-ready"
    generated = json.dumps(pipeline, ensure_ascii=False, indent=2) + "\n"
    committed = PIPELINE_GOLDEN_PATH.read_text(encoding="utf-8")

    _assert_golden_matches(generated, committed)


def test_python_trends_match_dashboard_golden(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    invalid = tmp_path / "invalid"
    _write_ready_channel(ready)
    _write_invalid_channel(invalid)
    server = create_server(port=0, channel_paths=[ready, invalid])
    try:
        trends: TrendsResponse = server.api.trends()
    finally:
        server.server_close()

    assert set(trends) == TrendsResponse.__required_keys__
    assert all(set(channel) == TrendChannelResponse.__required_keys__ for channel in trends["channels"])
    assert all(
        set(point) == TrendPointResponse.__required_keys__
        for channel in trends["channels"]
        for point in channel["points"]
    )
    trends["channels"][0]["id"] = "channel-ready"
    trends["channels"][1]["id"] = "channel-invalid"
    generated = json.dumps(trends, ensure_ascii=False, indent=2) + "\n"
    if os.environ.get(UPDATE_ENV) == "1":
        TRENDS_GOLDEN_PATH.write_text(generated, encoding="utf-8")
    if not TRENDS_GOLDEN_PATH.exists():
        pytest.fail(f"dashboard trends golden is missing. Generate it with: {REGEN_COMMAND}")

    committed = TRENDS_GOLDEN_PATH.read_text(encoding="utf-8")

    _assert_golden_matches(generated, committed)


def test_schema_drift_diagnostic_names_the_regeneration_command() -> None:
    with pytest.raises(AssertionError, match=UPDATE_ENV):
        _assert_golden_matches('{"schema_version": 3}\n', '{"schema_version": 2}\n')
