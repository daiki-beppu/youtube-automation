"""repo-local lite workflow（.takt/workflows/lite.yaml）の状態遷移契約を検証する。

takt の mock provider + TAKT_MOCK_SCENARIO（persona 別 fixture キュー）で、
LLM・ネットワークなしに structured verdict → transition → terminal state を
決定的に再現する。TAKT_CONFIG_DIR で擬似グローバル設定を注入するため、
実行環境の ~/.takt には依存しない（global schema 欠損の fail-closed も検証可能）。

前提（takt 0.51 系の観測仕様）:
- step 直指定の `provider:` は CLI `--provider` より優先されるため、
  fixture では YAML の step provider 値だけを mock に差し替える
- 複数 rule step の判定（phase 3）は persona "conductor" への structured 呼び出しで
  行われ、`{"step": N}`（1-based rule 番号）で遷移先が決まる
- loop monitor judge の本体呼び出しは judge の persona（supervisor）名で consume される

takt CLI が無い環境では skip する。CI の takt-workflow-contract job は
TAKT_LITE_CONTRACT_REQUIRED=1 で実行し、skip を許さない（黙って通さない）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LITE_WORKFLOW_PATH = _REPO_ROOT / ".takt" / "workflows" / "lite.yaml"
_TAKT_GLOBAL_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "takt_global"
_REQUIRED_ENV = "TAKT_LITE_CONTRACT_REQUIRED"
_TAKT_TIMEOUT_SECONDS = 180
_LOOP_JUDGE_STEP = "_loop_judge_implement_review"


def _require_takt() -> None:
    if shutil.which("takt") is not None:
        return
    if os.environ.get(_REQUIRED_ENV):
        pytest.fail(
            f"takt CLI が見つからない。{_REQUIRED_ENV} 指定時は skip を許さない"
            "（CI では npm install -g takt@<pinned> を先に実行すること）"
        )
    pytest.skip("takt CLI が無いためスキップ（CI の takt-workflow-contract job で実行される）")


@pytest.fixture(autouse=True)
def _takt_or_skip() -> None:
    _require_takt()


# --- scenario helpers -------------------------------------------------------


def _preflight(verdict: str = "approved") -> dict:
    return {
        "persona": "coder",
        "status": "done",
        "content": "preflight done",
        "structured_output": {"verdict": verdict, "feedback": "", "followups": []},
    }


def _review(verdict: str, content: str = "review done", feedback: str = "") -> dict:
    return {
        "persona": "architecture-reviewer",
        "status": "done",
        "content": content,
        "structured_output": {"verdict": verdict, "feedback": feedback, "followups": []},
    }


def _loop_judge(rule_number: int) -> list[dict]:
    """loop monitor judge 1 回分（phase 1 本体 + phase 3 structured 判定）。

    rule 番号は lite.yaml の loop_monitors.judge.rules の 1-based index
    （1 = 健全 → implement, 2 = 非生産的 → ABORT）。
    """
    return [
        {"persona": "supervisor", "status": "done", "content": f"judge rule {rule_number}"},
        {
            "persona": "conductor",
            "status": "done",
            "content": "judged",
            "structured_output": {"step": rule_number, "reason": "fixture judgment"},
        },
    ]


# --- runner -----------------------------------------------------------------


def _write_mock_workflow(dest: Path) -> None:
    """step 直指定 provider だけを mock に差し替えた lite.yaml を書き出す。

    step の `provider:` は CLI --provider より優先されるため、この差し替えなしでは
    mock provider に到達しない。rules / loop_monitors / structured_output などの
    契約対象はそのまま維持する。
    """
    data = yaml.safe_load(_LITE_WORKFLOW_PATH.read_text(encoding="utf-8"))
    for step in data["steps"]:
        if step.get("provider") == "codex":
            step["provider"] = "mock"
    dest.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _init_fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".takt" / "workflows").mkdir(parents=True)
    _write_mock_workflow(repo / ".takt" / "workflows" / "lite.yaml")
    (repo / ".takt" / "config.yaml").write_text(
        "provider: mock\ndraft_pr: false\nbase_branch: main\n", encoding="utf-8"
    )
    git_id = ["-c", "user.email=fixture@example.com", "-c", "user.name=fixture"]
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", *git_id, "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", *git_id, "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def _make_global_dir(tmp_path: Path, *, with_schema: bool) -> Path:
    global_dir = tmp_path / "takt_global"
    global_dir.mkdir()
    shutil.copy(_TAKT_GLOBAL_FIXTURE / "config.yaml", global_dir / "config.yaml")
    if with_schema:
        shutil.copytree(_TAKT_GLOBAL_FIXTURE / "schemas", global_dir / "schemas")
    return global_dir


def _takt_env(global_dir: Path, scenario_path: Path | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TAKT_")}
    env["TAKT_CONFIG_DIR"] = str(global_dir)
    env["TAKT_NO_TTY"] = "1"
    if scenario_path is not None:
        env["TAKT_MOCK_SCENARIO"] = str(scenario_path)
    return env


def _run_lite(
    tmp_path: Path, scenario: list[dict], *, with_schema: bool = True
) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
    repo = _init_fixture_repo(tmp_path)
    global_dir = _make_global_dir(tmp_path, with_schema=with_schema)
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(json.dumps(scenario, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        ["takt", "--pipeline", "--skip-git", "-q", "-w", "lite", "-t", "contract fixture task"],
        cwd=repo,
        env=_takt_env(global_dir, scenario_path),
        capture_output=True,
        text=True,
        timeout=_TAKT_TIMEOUT_SECONDS,
        check=False,
    )
    return proc, _load_trace(repo)


def _load_trace(repo: Path) -> list[dict]:
    logs = sorted((repo / ".takt" / "runs").glob("*/logs/*.jsonl"))
    if not logs:
        return []
    return [json.loads(line) for line in logs[-1].read_text(encoding="utf-8").splitlines() if line.strip()]


def _step_sequence(trace: list[dict]) -> list[str]:
    return [event["step"] for event in trace if event.get("type") == "step_start"]


def _terminal_event(trace: list[dict]) -> dict:
    terminals = [e for e in trace if e.get("type") in ("workflow_complete", "workflow_abort")]
    assert terminals, "terminal event (workflow_complete / workflow_abort) が記録されていない"
    return terminals[-1]


def _implement_instructions(trace: list[dict]) -> list[str]:
    return [
        event.get("instruction", "")
        for event in trace
        if event.get("type") == "phase_start" and event.get("step") == "implement" and event.get("phase") == 1
    ]


# --- 要件 1, 3: happy path（preflight approved → plan / review approved → COMPLETE） ---


def test_preflight_approved_reaches_complete_via_plan(tmp_path: Path) -> None:
    proc, trace = _run_lite(tmp_path, [_preflight("approved"), _review("approved")])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _step_sequence(trace) == ["preflight", "plan", "implement", "review"]
    assert _terminal_event(trace)["type"] == "workflow_complete"


# --- 要件 2: preflight blocked / 未知 verdict → ABORT ---


@pytest.mark.parametrize("verdict", ["blocked", "unexpected_verdict"])
def test_preflight_non_approved_aborts(tmp_path: Path, verdict: str) -> None:
    proc, trace = _run_lite(tmp_path, [_preflight(verdict)])
    assert proc.returncode != 0
    assert _step_sequence(trace) == ["preflight"]
    assert _terminal_event(trace)["type"] == "workflow_abort"


# --- 要件 4: review needs_fix → implement へ戻り feedback（review 応答）が注入される ---


def test_review_needs_fix_returns_to_implement_with_feedback(tmp_path: Path) -> None:
    feedback_marker = "REVIEW-FEEDBACK-ROUND-1: tests/test_x.py の assert が欠落"
    scenario = [
        _preflight("approved"),
        _review("needs_fix", content=feedback_marker, feedback=feedback_marker),
        _review("approved"),
    ]
    proc, trace = _run_lite(tmp_path, scenario)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _step_sequence(trace) == [
        "preflight",
        "plan",
        "implement",
        "review",
        "implement",
        "review",
    ]
    assert _terminal_event(trace)["type"] == "workflow_complete"
    instructions = _implement_instructions(trace)
    assert len(instructions) == 2
    assert feedback_marker not in instructions[0]
    assert feedback_marker in instructions[1], "差し戻し implement に review feedback が注入されていない"


# --- 要件 5: review blocked / 未知 verdict → ABORT ---


@pytest.mark.parametrize("verdict", ["blocked", "unexpected_verdict"])
def test_review_non_verdict_aborts(tmp_path: Path, verdict: str) -> None:
    proc, trace = _run_lite(tmp_path, [_preflight("approved"), _review(verdict)])
    assert proc.returncode != 0
    assert _step_sequence(trace) == ["preflight", "plan", "implement", "review"]
    assert _terminal_event(trace)["type"] == "workflow_abort"


# --- 要件 6: implement↔review 5 周で loop monitor judge が実行される ---


def test_loop_judge_unproductive_aborts(tmp_path: Path) -> None:
    scenario = [
        _preflight("approved"),
        _review("needs_fix", content="round 1"),
        _review("needs_fix", content="round 2"),
        _review("needs_fix", content="round 3"),
        _review("needs_fix", content="round 4"),
        _review("needs_fix", content="round 5"),
        *_loop_judge(2),
    ]
    proc, trace = _run_lite(tmp_path, scenario)
    assert proc.returncode != 0
    steps = _step_sequence(trace)
    assert steps.count("implement") == 5
    assert steps.count("review") == 5
    assert steps[-1] == _LOOP_JUDGE_STEP, "5 周目の review 完了後に loop judge が実行されていない"
    assert _terminal_event(trace)["type"] == "workflow_abort"


def test_loop_judge_healthy_continues_to_complete(tmp_path: Path) -> None:
    scenario = [
        _preflight("approved"),
        _review("needs_fix", content="round 1"),
        _review("needs_fix", content="round 2"),
        _review("needs_fix", content="round 3"),
        _review("needs_fix", content="round 4"),
        _review("needs_fix", content="round 5"),
        *_loop_judge(1),
        _review("approved"),
    ]
    proc, trace = _run_lite(tmp_path, scenario)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    steps = _step_sequence(trace)
    judge_index = steps.index(_LOOP_JUDGE_STEP)
    assert steps[judge_index:] == [_LOOP_JUDGE_STEP, "implement", "review"]
    assert _terminal_event(trace)["type"] == "workflow_complete"


# --- max_steps 契約: 上限到達で ABORT ---


def test_max_steps_aborts(tmp_path: Path) -> None:
    scenario = [
        _preflight("approved"),
        *[_review("needs_fix", content=f"round {i}") for i in range(1, 10)],
        *_loop_judge(1),
    ]
    proc, trace = _run_lite(tmp_path, scenario)
    assert proc.returncode != 0
    terminal = _terminal_event(trace)
    assert terminal["type"] == "workflow_abort"
    assert "Max steps" in terminal.get("reason", "")
    assert terminal.get("iterations") == 18, "lite.yaml の max_steps: 18 と一致しない"


# --- 要件 7: global schema 欠損の fail-closed ---


def test_missing_global_schema_fails_closed(tmp_path: Path) -> None:
    proc, trace = _run_lite(tmp_path, [_preflight("approved"), _review("approved")], with_schema=False)
    assert proc.returncode != 0, "review-verdict schema 欠損でも run が成功してしまった"
    assert "review-verdict" in proc.stdout + proc.stderr
    assert trace == [], "schema 欠損時は workflow 実行前に fail する契約"


def test_workflow_doctor_passes_against_repo_workflow(tmp_path: Path) -> None:
    global_dir = _make_global_dir(tmp_path, with_schema=True)
    proc = subprocess.run(
        ["takt", "workflow", "doctor", "lite"],
        cwd=_REPO_ROOT,
        env=_takt_env(global_dir),
        capture_output=True,
        text=True,
        timeout=_TAKT_TIMEOUT_SECONDS,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_workflow_doctor_fails_without_global_schema(tmp_path: Path) -> None:
    global_dir = _make_global_dir(tmp_path, with_schema=False)
    proc = subprocess.run(
        ["takt", "workflow", "doctor", "lite"],
        cwd=_REPO_ROOT,
        env=_takt_env(global_dir),
        capture_output=True,
        text=True,
        timeout=_TAKT_TIMEOUT_SECONDS,
        check=False,
    )
    assert proc.returncode != 0, "schema 欠損を doctor が検出できていない"
    assert "review-verdict" in proc.stdout + proc.stderr
