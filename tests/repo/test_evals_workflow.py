"""有料の skill E2E eval を独立 workflow で安全に実行する契約。"""

from __future__ import annotations

import yaml

from tests.helpers.paths import REPO_ROOT

WORKFLOW_PATH = REPO_ROOT / ".github/workflows/evals.yml"


def _workflow() -> dict[str, object]:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    return workflow


def _triggers(workflow: dict[str, object]) -> dict[str, object]:
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return triggers


def test_evals_workflow_is_manual_and_weekly_but_not_a_pr_gate() -> None:
    triggers = _triggers(_workflow())

    assert set(triggers) == {"workflow_dispatch", "schedule"}
    assert triggers["workflow_dispatch"] is None
    # 日次は対象 skill の変更頻度に対して過剰だったため週次にする（2026-08 監査）。
    assert triggers["schedule"] == [{"cron": "17 18 * * 1"}]


def test_missing_auth_explicitly_skips_the_paid_eval() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    auth = jobs["auth-check"]
    eval_job = jobs["eval"]
    auth_step = auth["steps"][0]

    assert workflow["permissions"] == {"contents": "read"}
    assert auth["outputs"] == {"available": "${{ steps.auth.outputs.available }}"}
    assert auth_step["env"] == {
        "CLAUDE_CODE_OAUTH_TOKEN": "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}",
        "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
    }
    auth_script = auth_step["run"]
    assert "available=false" in auth_script
    assert "::notice::" in auth_script
    assert "GITHUB_STEP_SUMMARY" in auth_script
    assert eval_job["needs"] == "auth-check"
    assert eval_job["if"] == "needs.auth-check.outputs.available == 'true'"


def test_authenticated_eval_uses_pinned_tools_and_reports_assertion_failures() -> None:
    eval_job = _workflow()["jobs"]["eval"]
    steps = eval_job["steps"]

    assert steps[0]["uses"] == "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    assert steps[1]["uses"] == "cachix/install-nix-action@630ae543ea3a38a9a4166f03376c02c50f408342"
    assert "@anthropic-ai/claude-code@2.1.226" in steps[2]["run"]

    promptfoo = next(step for step in steps if step.get("id") == "promptfoo")
    assert promptfoo["continue-on-error"] is True
    # pnpm / npm は .#extensions shell にしか無い（既定 shell では即死する）。
    assert "nix develop .#extensions --command pnpm dlx promptfoo@0.122.0 eval" in promptfoo["run"]
    assert "nix develop .#extensions --command npm install" in steps[2]["run"]
    assert "-c evals/promptfooconfig.yaml" in promptfoo["run"]
    assert "--output evals/results/ci.json" in promptfoo["run"]

    summary = next(step for step in steps if step.get("name") == "Summarize assertions")
    assert summary["if"] == "always()"
    assert "GITHUB_STEP_SUMMARY" in summary["run"]
    assert "gradingResult.componentResults" in summary["run"]
    assert ".assertion.metric" in summary["run"]
    assert ".reason" in summary["run"]

    failure = steps[-1]
    assert failure["if"] == "steps.promptfoo.outcome == 'failure'"
    assert "exit 1" in failure["run"]


def test_evals_remain_separate_from_the_required_ci_workflow() -> None:
    ci = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "promptfoo" not in ci
    assert "evals/promptfooconfig.yaml" not in ci
