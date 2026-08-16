"""`/analytics` の manifest と成果物鮮度判定の契約テスト。"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.core.errors import DocumentRenderError
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import publish_json_document

ROOT = REPO_ROOT
SKILL_DIR = ROOT / ".claude" / "skills" / "analytics"
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
    path = root / "reports" / "analysis_20260718.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "generated_at": "2026-07-18T00:00:00Z",
                "summary": "分析サマリ",
                "inputs": {},
                "cli_outputs": {},
                "vpd_ranking": {},
                "win_pattern": {},
                "strategic_improvements": [],
                "next_collection_candidates": [],
                "action_plan": [],
                "strategic_discussion": [],
            }
        ),
        encoding="utf-8",
    )
    html = publish_json_document(path, RepositorySchema.ANALYSIS_REPORT)
    os.utime(path, (timestamp, timestamp))
    os.utime(html, (timestamp, timestamp))


def test_manifest_declares_linear_gate_free_chain() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["chainId"] == "analytics"
    assert [step["id"] for step in manifest["steps"]] == ["collect", "analyze", "report"]
    assert [step["skill"] for step in manifest["steps"]] == [
        "analytics",
        "analytics",
        "analytics",
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
    assert result["freshness_source"] == ".claude/skills/analytics/config.default.yaml"


def test_collect_channel_override_changes_freshness_and_is_observable(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0
    override = tmp_path / "config" / "skills" / "analytics.yaml"
    override.parent.mkdir(parents=True)
    override.write_text("freshness_minutes: 5\n", encoding="utf-8")
    _touch(tmp_path / "data" / "analytics_data_20260718_120000.json", now - 6 * 60)

    code, result = state.evaluate(tmp_path, "collect", now)

    assert code == state.EXIT_RUN
    assert result["reason"] == "analytics_data_stale"
    assert result["freshness_minutes"] == 5
    assert result["freshness_source"] == "config/skills/analytics.yaml"


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


def test_invalid_or_stale_html_pair_is_not_successful(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0
    _touch(tmp_path / "data" / "analytics_data_20260718_120000.json", now - 10 * 60)
    _analysis_pair(tmp_path, now - 5 * 60)
    (tmp_path / "reports" / "analysis_20260718.html").write_text("stale", encoding="utf-8")

    with pytest.raises(DocumentRenderError, match="対応していません"):
        state.evaluate(tmp_path, "report", now)


def test_missing_and_stale_artifacts_cover_every_step(tmp_path: Path, state: ModuleType) -> None:
    now = 2_000_000_000.0

    collect_code, collect = state.evaluate(tmp_path, "collect", now)
    analyze_code, analyze = state.evaluate(tmp_path, "analyze", now)
    report_code, report = state.evaluate(tmp_path, "report", now)

    assert (collect_code, collect["decision"], collect["reason"]) == (
        state.EXIT_RUN,
        "run",
        "analytics_data_missing",
    )
    assert (analyze_code, analyze["decision"], analyze["reason"]) == (
        state.EXIT_BLOCKED,
        "blocked",
        "analytics_data_missing",
    )
    assert (report_code, report["decision"], report["reason"]) == (
        state.EXIT_BLOCKED,
        "blocked",
        "analytics_data_missing",
    )

    _touch(tmp_path / "data" / "analytics_data_20260718_120000.json", now - 31 * 60)
    for step in ("collect", "analyze", "report"):
        code, result = state.evaluate(tmp_path, step, now)
        assert result["artifacts"][0]["age_minutes"] == 31
        if step == "collect":
            assert (code, result["reason"]) == (state.EXIT_RUN, "analytics_data_stale")
        else:
            assert (code, result["reason"]) == (
                state.EXIT_BLOCKED,
                "analytics_data_stale_run_collect_first",
            )


def test_cli_emits_error_json_and_exit_two_for_invalid_freshness(tmp_path: Path) -> None:
    override = tmp_path / "config" / "skills" / "analytics.yaml"
    override.parent.mkdir(parents=True)
    override.write_text("freshness_minutes: 0\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--channel-dir",
            str(tmp_path),
            "--step",
            "collect",
            "--now",
            "2000000000",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["step"] == "collect"
    assert payload["decision"] == "error"
    assert payload["artifacts"] == []
    assert "正の数" in payload["reason"]


def test_analytics_description_exposes_every_exclusive_mode() -> None:
    text = (ROOT / ".claude" / "skills" / "analytics" / "SKILL.md").read_text(encoding="utf-8")
    description = text.split("---", 2)[1]

    assert all(flag in description for flag in ("--collect", "--analyze", "--report"))
