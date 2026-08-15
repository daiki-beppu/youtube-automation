"""`/channel-research` chain の成果物判定契約。"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.core.errors import DocumentRenderError
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import publish_json_document

SCRIPT = REPO_ROOT / ".claude" / "skills" / "channel-research" / "references" / "channel-research-chain-state.py"


@pytest.fixture
def state() -> ModuleType:
    spec = importlib.util.spec_from_file_location("channel_research_chain_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _touch(path: Path, timestamp: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    os.utime(path, (timestamp, timestamp))


def _publish_report(path: Path, report_type: str, timestamp: float) -> None:
    document = {
        "schema_version": 1,
        "generated_at": "2026-08-16T00:00:00Z",
        "report_type": report_type,
        "summary": "summary",
        "source_provenance": [{"path": "data/source.json", "collected_at": "2026-08-16", "claim": "claim"}],
        "competitor_comparison": [],
        "winning_patterns": [],
        "evidence": [{"id": "ev-1", "source_path": "data/source.json", "observation": "fact"}],
        "application_candidates": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    html = publish_json_document(path, RepositorySchema.CHANNEL_RESEARCH_REPORT)
    os.utime(path, (timestamp, timestamp))
    os.utime(html, (timestamp, timestamp))


def test_missing_channel_config_blocks_before_collection(tmp_path: Path, state: ModuleType) -> None:
    code, result = state.evaluate(tmp_path, "benchmark", 2_000_000_000.0)

    assert code == state.EXIT_BLOCKED
    assert result["reason"] == "config_channel_analytics_missing"


def test_missing_outputs_run_and_fresh_outputs_skip(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0
    _touch(tmp_path / "config/channel/analytics.json", now)

    code, result = state.evaluate(tmp_path, "benchmark", now)
    assert code == state.EXIT_RUN
    assert result["reason"] == "benchmark_outputs_missing"

    _touch(tmp_path / "data/benchmark_20260815.json", now - 60)
    _publish_report(tmp_path / "docs/benchmarks/benchmark-report.json", "benchmark", now - 60)
    code, result = state.evaluate(tmp_path, "benchmark", now)
    assert code == state.EXIT_SKIP
    assert result["freshness_days"] == 3
    assert result["freshness_source"] == ".claude/skills/channel-research/config.default.yaml"


def test_legacy_override_controls_stale_decision(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0
    _touch(tmp_path / "config/channel/analytics.json", now)
    override = tmp_path / "config/skills/benchmark.yaml"
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text("freshness_days: 1\n", encoding="utf-8")
    _touch(tmp_path / "data/benchmark_20260815.json", now - 86_401)
    _publish_report(tmp_path / "docs/benchmarks/benchmark-report.json", "benchmark", now - 86_401)

    code, result = state.evaluate(tmp_path, "benchmark", now)

    assert code == state.EXIT_RUN
    assert result["reason"] == "benchmark_outputs_stale"
    assert result["freshness_source"] == "config/skills/benchmark.yaml"


def test_discover_blocks_without_benchmark_and_runs_without_output(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0

    blocked_code, blocked = state.evaluate(tmp_path, "discover", now)
    _publish_report(tmp_path / "docs/benchmarks/benchmark-report.json", "benchmark", now)
    run_code, run = state.evaluate(tmp_path, "discover", now)

    assert blocked_code == state.EXIT_BLOCKED
    assert blocked["reason"] == "benchmark_reports_missing"
    assert run_code == state.EXIT_RUN
    assert run["reason"] == "discover_outputs_missing"


def test_discover_skips_only_for_complete_output_pair(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0
    _publish_report(tmp_path / "docs/benchmarks/benchmark-report.json", "benchmark", now)
    _touch(tmp_path / "research/lofi-discovery.md", now)

    run_code, run = state.evaluate(tmp_path, "discover", now)
    _touch(tmp_path / "research/lofi-discovery.csv", now)
    skip_code, skip = state.evaluate(tmp_path, "discover", now)

    assert run_code == state.EXIT_RUN
    assert run["reason"] == "discover_output_pair_incomplete"
    assert skip_code == state.EXIT_SKIP
    assert skip["reason"] == "discover_output_pair_complete"


def test_voice_blocks_until_benchmark_and_discover_outputs_exist(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0
    _touch(tmp_path / "data/benchmark_20260815.json", now)
    _publish_report(tmp_path / "docs/benchmarks/benchmark-report.json", "benchmark", now)

    code, result = state.evaluate(tmp_path, "voice", now)

    assert code == state.EXIT_BLOCKED
    assert result["reason"] == "voice_prerequisites_missing"


def test_voice_runs_and_skips_only_after_both_outputs_exist(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0
    for relative in (
        "data/benchmark_20260815.json",
        "research/lofi-discovery.md",
        "research/lofi-discovery.csv",
    ):
        _touch(tmp_path / relative, now)
    _publish_report(tmp_path / "docs/benchmarks/benchmark-report.json", "benchmark", now)

    run_code, run = state.evaluate(tmp_path, "voice", now)
    _touch(tmp_path / "data/comments_20260815.json", now)
    partial_code, partial = state.evaluate(tmp_path, "voice", now)
    _publish_report(tmp_path / "docs/plans/viewer-voice-analysis.json", "viewer_voice", now)
    skip_code, skip = state.evaluate(tmp_path, "voice", now)

    assert run_code == state.EXIT_RUN
    assert run["reason"] == "voice_outputs_missing"
    assert partial_code == state.EXIT_RUN
    assert partial["reason"] == "voice_outputs_incomplete"
    assert skip_code == state.EXIT_SKIP
    assert skip["reason"] == "voice_outputs_complete"


def test_market_uses_comparison_branch_when_collected_inputs_are_absent(tmp_path: Path, state: ModuleType) -> None:
    code, result = state.evaluate(tmp_path, "market", 2_000_000_000.0)

    assert code == state.EXIT_RUN
    assert result["branch"] == "market-comparison"
    assert result["reason"] == "market_comparison_required"


def test_market_blocks_partial_collected_analysis_inputs(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0
    _touch(tmp_path / "data/benchmark_20260815.json", now)

    code, result = state.evaluate(tmp_path, "market", now)

    assert code == state.EXIT_BLOCKED
    assert result["branch"] == "collected-analysis"
    assert result["reason"] == "collected_analysis_inputs_incomplete"


def test_market_skips_only_after_both_collected_analysis_outputs_exist(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0
    _touch(tmp_path / "data/benchmark_20260815.json", now)
    _touch(tmp_path / "data/comments_20260815.json", now)
    _publish_report(tmp_path / "docs/benchmarks/benchmark-report.json", "benchmark", now)

    run_code, run = state.evaluate(tmp_path, "market", now)
    _publish_report(tmp_path / "docs/channel-research.json", "market", now)
    skip_code, skip = state.evaluate(tmp_path, "market", now)

    assert run_code == state.EXIT_RUN
    assert run["branch"] == "collected-analysis"
    assert run["reason"] == "collected_analysis_outputs_missing"
    assert skip_code == state.EXIT_SKIP
    assert skip["reason"] == "collected_analysis_outputs_complete"


def test_mismatched_html_pair_is_fail_closed(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0
    _touch(tmp_path / "config/channel/analytics.json", now)
    _touch(tmp_path / "data/benchmark_20260815.json", now)
    report = tmp_path / "docs/benchmarks/benchmark-report.json"
    _publish_report(report, "benchmark", now)
    report.with_suffix(".html").write_text("tampered", encoding="utf-8")

    with pytest.raises(DocumentRenderError, match="JSON と HTML が対応していません"):
        state.evaluate(tmp_path, "benchmark", now)
