"""`.github/scripts/pyscn-diff-gate.py` の new-only 突き合わせ契約（#4616）。

#4615 の閾値ゲートは既存債務を追認した実測値が上限になるため、base commit に
無い finding が増えたときだけ fail する差分ゲートを独立に持つ。突き合わせ鍵は
行番号を含めない（ファイルパス + finding 種別 + シンボル名）ことが要件のため、
行ずれで同一性が壊れないことをここで固定する。
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import yaml

from tests.helpers.paths import REPO_ROOT

_GATE_SCRIPT = REPO_ROOT / ".github" / "scripts" / "pyscn-diff-gate.py"
_CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_gate_module():
    spec = importlib.util.spec_from_file_location("pyscn_diff_gate", _GATE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_gate = _load_gate_module()


# --- 突き合わせロジック（synthetic report は実 pyscn 1.29.1 の JSON schema を鏡像する） ---


def _complexity_function(
    file_path: str,
    name: str,
    risk_level: str,
    *,
    start_line: int = 10,
    complexity: int = 24,
) -> dict:
    return {
        "Name": name,
        "FilePath": file_path,
        "StartLine": start_line,
        "StartColumn": 0,
        "EndLine": start_line + 12,
        "Metrics": {
            "Complexity": complexity,
            "CognitiveComplexity": complexity,
            "Nodes": 12,
            "Edges": 18,
            "NestingDepth": 3,
            "IfStatements": 4,
            "LoopStatements": 1,
            "ExceptionHandlers": 0,
            "SwitchCases": 0,
            "SLOC": 13,
        },
        "RiskLevel": risk_level,
    }


def _dead_code_file(
    file_path: str,
    function_name: str,
    reason: str,
    *,
    start_line: int = 5,
) -> dict:
    return {
        "file_path": file_path,
        "functions": [
            {
                "name": function_name,
                "file_path": file_path,
                "findings": [
                    {
                        "location": {
                            "file_path": file_path,
                            "start_line": start_line,
                            "end_line": start_line,
                            "start_column": 0,
                            "end_column": 0,
                        },
                        "function_name": function_name,
                        "code": "Call",
                        "reason": reason,
                        "severity": "critical",
                        "description": "Code appears after a return statement and will never be executed",
                        "block_id": "bb6",
                    }
                ],
                "total_blocks": 7,
                "dead_blocks": 1,
                "reachable_ratio": 0.71,
                "critical_count": 1,
                "warning_count": 0,
                "info_count": 0,
            }
        ],
        "total_findings": 1,
        "total_functions": 1,
        "affected_functions": 1,
        "dead_code_ratio": 0.14,
    }


def _report(
    *,
    functions: list[dict] | None = None,
    dead_code_files: list[dict] | None = None,
) -> dict:
    # pyscn は finding が 0 件のコレクションを空リストではなく null で出力する。
    # None をそのまま渡すことでその実 schema を再現する。
    return {
        "complexity": {"Functions": functions},
        "dead_code": {"files": dead_code_files},
    }


def test_high_risk_function_is_reported_as_finding() -> None:
    report = _report(functions=[_complexity_function("src/youtube_automation/mod.py", "busy", "high")])

    findings = _gate.extract_findings(report)

    assert findings == {
        ("src/youtube_automation/mod.py", "complexity/high_risk", "busy"),
    }


def test_low_and_medium_risk_functions_are_not_findings() -> None:
    report = _report(
        functions=[
            _complexity_function("src/youtube_automation/mod.py", "simple", "low", complexity=2),
            _complexity_function("src/youtube_automation/mod.py", "middling", "medium", complexity=12),
        ]
    )

    assert _gate.extract_findings(report) == set()


def test_dead_code_finding_is_keyed_by_file_reason_and_function() -> None:
    report = _report(
        dead_code_files=[_dead_code_file("src/youtube_automation/mod.py", "sneaky", "unreachable_after_return")]
    )

    findings = _gate.extract_findings(report)

    assert findings == {
        (
            "src/youtube_automation/mod.py",
            "dead_code/unreachable_after_return",
            "sneaky",
        ),
    }


def test_null_finding_collections_yield_no_findings() -> None:
    assert _gate.extract_findings(_report()) == set()


def test_line_shift_does_not_change_finding_identity() -> None:
    base = _report(
        functions=[_complexity_function("src/youtube_automation/mod.py", "busy", "high", start_line=10)],
        dead_code_files=[
            _dead_code_file("src/youtube_automation/mod.py", "sneaky", "unreachable_after_return", start_line=5)
        ],
    )
    head = _report(
        functions=[_complexity_function("src/youtube_automation/mod.py", "busy", "high", start_line=42)],
        dead_code_files=[
            _dead_code_file("src/youtube_automation/mod.py", "sneaky", "unreachable_after_return", start_line=37)
        ],
    )

    assert _gate.resolve_new_findings(base, head) == []


def test_only_findings_absent_from_base_are_new() -> None:
    base = _report(
        functions=[_complexity_function("src/youtube_automation/legacy.py", "legacy_debt", "high")],
        dead_code_files=[_dead_code_file("src/youtube_automation/legacy.py", "gone", "unreachable_after_return")],
    )
    head = _report(
        functions=[
            _complexity_function("src/youtube_automation/legacy.py", "legacy_debt", "high"),
            _complexity_function("src/youtube_automation/fresh.py", "newcomer", "high"),
        ]
    )

    assert _gate.resolve_new_findings(base, head) == [
        ("src/youtube_automation/fresh.py", "complexity/high_risk", "newcomer"),
    ]


# --- ゲート実行（実 git + 実 pyscn。base commit を worktree へ展開して 2 回解析する） ---


_GIT_ENVIRONMENT = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "pyscn-diff-gate-test",
    "GIT_AUTHOR_EMAIL": "pyscn-diff-gate-test@example.invalid",
    "GIT_COMMITTER_NAME": "pyscn-diff-gate-test",
    "GIT_COMMITTER_EMAIL": "pyscn-diff-gate-test@example.invalid",
}


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        env=os.environ | _GIT_ENVIRONMENT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _branchy_source(name: str, branches: int = 25) -> str:
    # if/elif 連鎖で cyclomatic complexity を branches+1 に固定し、pyscn の既定
    # medium_threshold(19) を超える high risk finding を決定的に作る。
    lines = [f"def {name}(value: int) -> int:", "    result = 0", "    if value == 0:", "        result = 0"]
    for index in range(1, branches):
        lines.append(f"    elif value == {index}:")
        lines.append(f"        result = {index}")
    lines.append("    return result")
    return "\n".join(lines) + "\n"


_DEAD_CODE_SOURCE = """def sneaky(flag: bool) -> int:
    if flag:
        return 1
    return 0
    print("never")
"""


def _build_repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    package_dir = repository / "src" / "youtube_automation"
    package_dir.mkdir(parents=True)
    _git(repository, "init", "-q", "-b", "work")

    (package_dir / "legacy.py").write_text(_branchy_source("legacy_debt"), encoding="utf-8")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "-m", "base")
    base_sha = _git(repository, "rev-parse", "HEAD")
    return repository, base_sha


def _run_gate(repository: Path, base_sha: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ | _GIT_ENVIRONMENT | {"PYSCN_DIFF_BASE": base_sha}
    return subprocess.run(
        [sys.executable, str(_GATE_SCRIPT)],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_gate_fails_on_new_finding_and_reports_only_the_new_one(tmp_path: Path) -> None:
    repository, base_sha = _build_repository(tmp_path)
    (repository / "src" / "youtube_automation" / "fresh.py").write_text(_DEAD_CODE_SOURCE, encoding="utf-8")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "-m", "add dead code")

    result = _run_gate(repository, base_sha)

    combined_output = result.stdout + result.stderr
    assert result.returncode == 1, combined_output
    assert "fresh.py" in combined_output
    # base にも存在する finding（legacy_debt）は出力しない。
    assert "legacy_debt" not in combined_output


def test_gate_passes_when_existing_findings_only_shift_lines(tmp_path: Path) -> None:
    repository, base_sha = _build_repository(tmp_path)
    legacy_path = repository / "src" / "youtube_automation" / "legacy.py"
    shifted = "GREETING = 'hello'\n\n\n" + legacy_path.read_text(encoding="utf-8")
    legacy_path.write_text(shifted, encoding="utf-8")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "-m", "shift lines without new findings")

    result = _run_gate(repository, base_sha)

    assert result.returncode == 0, result.stdout + result.stderr
    # base の一時 worktree を後片付けしていること（メイン worktree の 1 行だけ残る）。
    assert len(_git(repository, "worktree", "list", "--porcelain").split("\n\n")) == 1


# --- CI 配線（lint ジョブから到達できること） ---


def test_ci_lint_wires_the_diff_gate_step() -> None:
    workflow = yaml.safe_load(_CI_WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["lint"]["steps"]

    checkout = next(step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@"))
    assert checkout.get("with") == {"fetch-depth": 0}

    gate_step = next(step for step in steps if "pyscn-diff-gate.py" in str(step.get("run", "")))
    assert gate_step.get("if") == "needs.changes.outputs.python == 'true'"
    assert gate_step.get("env") == {
        "EVENT_NAME": "${{ github.event_name }}",
        "PR_BASE_SHA": "${{ github.event.pull_request.base.sha }}",
        "PUSH_BEFORE_SHA": "${{ github.event.before }}",
    }
    run_script = gate_step["run"]
    # main push は event.before、空・全 0 SHA は HEAD^ へ fallback する（classify と同じ規則）。
    assert "PUSH_BEFORE_SHA" in run_script
    assert "0000000000000000000000000000000000000000" in run_script
    assert "PYSCN_DIFF_BASE" in run_script
