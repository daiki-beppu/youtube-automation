"""`/analytics-run` の manifest と成果物鮮度判定の契約テスト。"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / ".claude" / "skills" / "analytics-run"
SCRIPT = SKILL_DIR / "references" / "analytics-chain-state.py"
MANIFEST = SKILL_DIR / "references" / "analytics-chain-manifest.json"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("analytics_chain_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def state() -> ModuleType:
    return _load_module()


def _touch(path: Path, timestamp: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    os.utime(path, (timestamp, timestamp))


def _analysis_pair(root: Path, timestamp: float) -> None:
    _touch(root / "reports" / "analysis_20260718.md", timestamp)
    _touch(root / "reports" / "analysis_20260718.json", timestamp)


def test_manifest_declares_linear_gate_free_chain() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["chainId"] == "analytics"
    assert [step["id"] for step in manifest["steps"]] == ["collect", "analyze", "report"]
    assert [step["skill"] for step in manifest["steps"]] == [
        "analytics-collect",
        "analytics-analyze",
        "analytics-report",
    ]
    assert all(step["approvalGate"]["skip"] is True for step in manifest["steps"])
    assert all("enabled" not in step["approvalGate"] for step in manifest["steps"])
    assert all(".skip_approvals." in step["approvalGate"]["configPath"] for step in manifest["steps"])
    assert {step["idempotency"]["script"] for step in manifest["steps"]} == {"references/analytics-chain-state.py"}


def test_collect_uses_default_freshness_and_exposes_source(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0
    _touch(tmp_path / "data" / "analytics_data_20260718_120000.json", now - 29 * 60)

    code, result = state.evaluate(tmp_path, "collect", now)

    assert code == state.EXIT_SKIP
    assert result["decision"] == "skip"
    assert result["freshness_minutes"] == 30
    assert result["freshness_source"] == ".claude/skills/analytics-collect/config.default.yaml"


def test_collect_channel_override_changes_freshness_and_is_observable(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0
    override = tmp_path / "config" / "skills" / "analytics-collect.yaml"
    override.parent.mkdir(parents=True)
    override.write_text("freshness_minutes: 5\n", encoding="utf-8")
    _touch(tmp_path / "data" / "analytics_data_20260718_120000.json", now - 6 * 60)

    code, result = state.evaluate(tmp_path, "collect", now)

    assert code == state.EXIT_RUN
    assert result["reason"] == "analytics_data_stale"
    assert result["freshness_minutes"] == 5
    assert result["freshness_source"] == "config/skills/analytics-collect.yaml"


def test_analyze_skips_fresh_pair_newer_than_analytics(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0
    _touch(tmp_path / "data" / "analytics_data_20260718_120000.json", now - 10 * 60)
    _analysis_pair(tmp_path, now - 5 * 60)

    code, result = state.evaluate(tmp_path, "analyze", now)

    assert code == state.EXIT_SKIP
    assert result["reason"] == "analysis_pair_fresh"


def test_analyze_reruns_pair_older_than_latest_analytics(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0
    _analysis_pair(tmp_path, now - 10 * 60)
    _touch(tmp_path / "data" / "analytics_data_20260718_120000.json", now - 5 * 60)

    code, result = state.evaluate(tmp_path, "analyze", now)

    assert code == state.EXIT_RUN
    assert result["reason"] == "analysis_pair_older_than_analytics_data"


def test_report_is_blocked_without_analysis_and_runs_when_ready(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0
    _touch(tmp_path / "data" / "analytics_data_20260718_120000.json", now - 10 * 60)

    blocked_code, blocked = state.evaluate(tmp_path, "report", now)
    _analysis_pair(tmp_path, now - 5 * 60)
    run_code, ready = state.evaluate(tmp_path, "report", now)

    assert blocked_code == state.EXIT_BLOCKED
    assert blocked["reason"] == "analysis_pair_missing"
    assert run_code == state.EXIT_RUN
    assert ready["reason"] == "latest_report_ready_for_display"


def test_existing_skills_route_whole_chain_to_analytics_run() -> None:
    for name in ("analytics-collect", "analytics-analyze", "analytics-report"):
        text = (ROOT / ".claude" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        description = text.split("---", 2)[1]
        assert "/analytics-run" in description
