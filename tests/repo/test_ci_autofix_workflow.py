"""CI 失敗の自動修正を post-push の保険ゲートとして安全に実行する契約。"""

from __future__ import annotations

import re

import yaml

from tests.helpers.paths import REPO_ROOT

WORKFLOW_PATH = REPO_ROOT / ".github/workflows/ci-autofix.yml"
WORKFLOWS_DIR = REPO_ROOT / ".github/workflows"

# PR をゲートする workflow だけが対象(evals / release-extensions は schedule / tag トリガー)
WATCHED_WORKFLOWS = ["CI", "Dashboard", "Extensions", "Audio Studio", "Release notes site"]

_PINNED_ACTION = re.compile(r"^anthropics/claude-code-action@[0-9a-f]{40}$")


def _workflow() -> dict[str, object]:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    return workflow


def _triggers(workflow: dict[str, object]) -> dict[str, object]:
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return triggers


def _decide_step(gate_job: dict[str, object]) -> dict[str, object]:
    return next(step for step in gate_job["steps"] if step.get("id") == "decide")


def _autofix_step(autofix_job: dict[str, object]) -> dict[str, object]:
    return next(step for step in autofix_job["steps"] if step.get("id") == "autofix")


def test_autofix_fires_when_a_pr_gate_workflow_fails() -> None:
    triggers = _triggers(_workflow())

    assert set(triggers) == {"workflow_run"}
    assert triggers["workflow_run"] == {
        "workflows": WATCHED_WORKFLOWS,
        "types": ["completed"],
    }


def test_watched_workflow_names_match_existing_workflow_files() -> None:
    names = set()
    for path in WORKFLOWS_DIR.glob("*.yml"):
        definition = yaml.safe_load(path.read_text(encoding="utf-8"))
        names.add(definition.get("name"))

    # 対象 workflow の rename で autofix が黙って発火しなくなる drift を検出する
    assert set(WATCHED_WORKFLOWS) <= names


def test_gate_only_processes_failed_pr_runs_from_the_same_repo() -> None:
    gate = _workflow()["jobs"]["gate"]["if"]

    assert "github.event.workflow_run.conclusion == 'failure'" in gate
    assert "github.event.workflow_run.event == 'pull_request'" in gate
    # fork からの PR は対象外
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in gate


def test_missing_auth_explicitly_skips_the_paid_fix() -> None:
    gate = _workflow()["jobs"]["gate"]
    auth_step = gate["steps"][0]

    assert auth_step["env"] == {
        "CLAUDE_CODE_OAUTH_TOKEN": "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}",
        "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
    }
    auth_script = auth_step["run"]
    assert "available=false" in auth_script
    assert "::notice::" in auth_script
    assert _decide_step(gate)["if"] == "steps.auth.outputs.available == 'true'"


def test_draft_skip_label_and_stale_head_opt_out_of_the_fix() -> None:
    workflow = _workflow()
    decide_script = _decide_step(workflow["jobs"]["gate"])["run"]

    assert "isDraft" in decide_script
    assert "skip-autofix" in decide_script
    # 失敗した commit から head が進んでいたら、新しい push の CI に判定を譲る
    assert "headRefOid" in decide_script
    assert "FAILED_HEAD_SHA" in decide_script

    autofix = workflow["jobs"]["autofix"]
    assert autofix["needs"] == "gate"
    assert autofix["if"] == "needs.gate.outputs.proceed == 'true'"


def test_fix_attempts_are_limited_to_one_per_pr() -> None:
    workflow = _workflow()
    decide_script = _decide_step(workflow["jobs"]["gate"])["run"]

    # 自動修正 commit のマーカーを検出したら再修正せずコメント報告のみ
    assert "[ci-autofix]" in decide_script
    assert "gh pr comment" in decide_script

    prompt = _autofix_step(workflow["jobs"]["autofix"])["with"]["prompt"]
    assert "[ci-autofix]" in prompt


def test_fix_pushes_via_app_token_to_retrigger_ci() -> None:
    workflow = _workflow()

    # GITHUB_TOKEN の push は pull_request: synchronize を発火させないため、
    # 既定の OIDC → Claude App トークン交換(id-token: write)で push する。
    # contents: read は「GITHUB_TOKEN では push できない」ことの機械担保でもある
    assert workflow["permissions"] == {
        "contents": "read",
        "pull-requests": "write",
        "issues": "read",
        "actions": "read",
        "id-token": "write",
    }
    for job in workflow["jobs"].values():
        assert "permissions" not in job

    step = _autofix_step(workflow["jobs"]["autofix"])
    assert "github_token" not in step["with"]


def test_autofix_installs_the_pinned_action_with_opus() -> None:
    step = _autofix_step(_workflow()["jobs"]["autofix"])

    assert _PINNED_ACTION.match(step["uses"])
    assert "--model opus" in step["with"]["claude_args"]


def test_autofix_can_edit_files_and_run_project_quality_gates() -> None:
    claude_args = _autofix_step(_workflow()["jobs"]["autofix"])["with"]["claude_args"]

    assert "Edit" in claude_args
    assert "Write" in claude_args
    assert "Bash(uv run ruff:*)" in claude_args
    assert "Bash(uv run pytest:*)" in claude_args


def test_concurrent_failures_for_one_branch_do_not_stack_fixes() -> None:
    concurrency = _workflow()["concurrency"]

    assert "github.event.workflow_run.head_branch" in concurrency["group"]
    # 進行中の修正を途中で殺さない。2 本目以降は queue され、gate の head_sha 照合で skip される
    assert concurrency["cancel-in-progress"] is False
