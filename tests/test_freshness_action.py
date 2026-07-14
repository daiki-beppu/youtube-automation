from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_RUNNER = Path(__file__).resolve().parents[1] / ".claude/skills/collection-ideate/references/freshness_action.py"


def _run(tmp_path: Path, *args: str) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = subprocess.run(
        [sys.executable, str(_RUNNER), "--reports-dir", str(tmp_path / "reports"), "--usd-per-kib", "0.01", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result, json.loads(result.stdout)


def _report(tmp_path: Path, size: int = 1024) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "analysis_20260714.md").write_bytes(b"x" * size)


def test_ask_first_stage_returns_estimate_and_exact_three_choices(tmp_path: Path) -> None:
    _report(tmp_path)
    result, payload = _run(tmp_path, "--action", "ask", "--stale-kind", "relative")
    assert result.returncode == 0
    assert payload == {
        "action": "ask",
        "estimate_usd": 0.01,
        "report_count": 1,
        "reason": None,
        "outcome": "ask",
        "choices": ["auto", "manual", "abort"],
        "skills": [],
    }


def test_ask_second_stage_maps_every_choice(tmp_path: Path) -> None:
    _report(tmp_path)
    expected = {
        "auto": ("execute", ["analytics-analyze"]),
        "manual": ("manual", []),
        "abort": ("abort", []),
    }
    for choice, (outcome, skills) in expected.items():
        result, payload = _run(tmp_path, "--action", "ask", "--choice", choice, "--stale-kind", "relative")
        assert result.returncode == 0
        assert payload["outcome"] == outcome
        assert payload["skills"] == skills


def test_auto_over_limit_falls_back_to_real_first_stage_question(tmp_path: Path) -> None:
    _report(tmp_path)
    result, payload = _run(
        tmp_path,
        "--action",
        "auto",
        "--stale-kind",
        "relative",
        "--auto-run-max-cost-usd",
        "0.001",
    )
    assert result.returncode == 0
    assert payload["action"] == "ask"
    assert payload["outcome"] == "ask"
    assert payload["choices"] == ["auto", "manual", "abort"]
    assert "auto_run_max_cost_usd" in str(payload["reason"])


def test_auto_unknown_estimate_falls_back_to_real_first_stage_question(tmp_path: Path) -> None:
    result, payload = _run(tmp_path, "--action", "auto", "--stale-kind", "relative")
    assert result.returncode == 0
    assert payload["action"] == "ask"
    assert payload["outcome"] == "ask"
    assert payload["estimate_usd"] is None
    assert payload["choices"] == ["auto", "manual", "abort"]
    assert "見積不能" in str(payload["reason"])


def test_auto_within_limit_requests_skills_in_production_order(tmp_path: Path) -> None:
    _report(tmp_path)
    relative = _run(tmp_path, "--action", "auto", "--stale-kind", "relative")[1]
    absolute = _run(tmp_path, "--action", "auto", "--stale-kind", "absolute")[1]
    assert relative["outcome"] == "execute"
    assert relative["skills"] == ["analytics-analyze"]
    assert absolute["outcome"] == "execute"
    assert absolute["skills"] == ["analytics-collect", "analytics-analyze"]
    assert relative["workflow"] == {"outcome": "tool_call", "skill": "analytics-analyze", "message": None}
    assert absolute["workflow"] == {"outcome": "tool_call", "skill": "analytics-collect", "message": None}


def test_execute_path_calls_every_skill_then_revalidates_and_continues(tmp_path: Path) -> None:
    _report(tmp_path)
    first = _run(tmp_path, "--action", "auto", "--stale-kind", "absolute")[1]
    assert first["workflow"]["skill"] == "analytics-collect"

    second = _run(tmp_path, "--action", "auto", "--stale-kind", "absolute", "--skill-result", "success")[1]
    assert second["workflow"]["skill"] == "analytics-analyze"

    third = _run(
        tmp_path,
        "--action",
        "auto",
        "--stale-kind",
        "absolute",
        "--skill-result",
        "success",
        "--skill-result",
        "success",
    )[1]
    assert third["workflow"]["outcome"] == "revalidate"

    final = _run(
        tmp_path,
        "--action",
        "auto",
        "--stale-kind",
        "absolute",
        "--skill-result",
        "success",
        "--skill-result",
        "success",
        "--revalidation",
        "success",
    )[1]
    assert final["workflow"]["outcome"] == "continue"


def test_skill_or_revalidation_failure_stops_before_continue(tmp_path: Path) -> None:
    _report(tmp_path)
    skill_result, skill_payload = _run(
        tmp_path, "--action", "auto", "--stale-kind", "relative", "--skill-result", "failure"
    )
    assert skill_result.returncode == 1
    assert skill_payload["workflow"]["outcome"] == "error"
    assert "Skill 呼び出し失敗" in skill_payload["workflow"]["message"]

    validation_result, validation_payload = _run(
        tmp_path,
        "--action",
        "auto",
        "--stale-kind",
        "relative",
        "--skill-result",
        "success",
        "--revalidation",
        "failure",
    )
    assert validation_result.returncode == 1
    assert validation_payload["workflow"]["outcome"] == "error"
    assert "企画生成へ進まず停止" in validation_payload["workflow"]["message"]


def test_manual_preserves_stop_without_skill_request(tmp_path: Path) -> None:
    _report(tmp_path)
    result, payload = _run(tmp_path, "--action", "manual", "--stale-kind", "absolute")
    assert result.returncode == 0
    assert payload["outcome"] == "manual"
    assert payload["skills"] == []
