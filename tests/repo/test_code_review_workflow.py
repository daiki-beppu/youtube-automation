"""PR 自動コードレビューをマージ前ゲートとして安全に実行する契約。"""

from __future__ import annotations

import re

import yaml

from tests.helpers.paths import REPO_ROOT

WORKFLOW_PATH = REPO_ROOT / ".github/workflows/code-review.yml"

_PINNED_ACTION = re.compile(r"^anthropics/claude-code-action@[0-9a-f]{40}$")


def _workflow() -> dict[str, object]:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    return workflow


def _triggers(workflow: dict[str, object]) -> dict[str, object]:
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    return triggers


def _review_step(review_job: dict[str, object]) -> dict[str, object]:
    return next(step for step in review_job["steps"] if step.get("id") == "review")


def test_review_fires_on_non_draft_pr_updates() -> None:
    triggers = _triggers(_workflow())

    assert set(triggers) == {"pull_request"}
    assert triggers["pull_request"] == {"types": ["opened", "ready_for_review", "synchronize"]}


def test_successive_pushes_cancel_the_in_progress_run() -> None:
    concurrency = _workflow()["concurrency"]

    assert "github.event.pull_request.number" in concurrency["group"]
    assert concurrency["cancel-in-progress"] is True


def test_draft_and_skip_review_label_opt_out_of_the_review() -> None:
    gate = _workflow()["jobs"]["auth-check"]["if"]

    assert gate == (
        "${{ !github.event.pull_request.draft && !contains(github.event.pull_request.labels.*.name, 'skip-review') }}"
    )


def test_missing_auth_explicitly_skips_the_paid_review() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    auth = jobs["auth-check"]
    review = jobs["review"]
    auth_step = auth["steps"][0]

    assert auth["outputs"] == {"available": "${{ steps.auth.outputs.available }}"}
    assert auth_step["env"] == {
        "CLAUDE_CODE_OAUTH_TOKEN": "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}",
        "ANTHROPIC_API_KEY": "${{ secrets.ANTHROPIC_API_KEY }}",
    }
    auth_script = auth_step["run"]
    assert "available=false" in auth_script
    assert "::notice::" in auth_script
    assert review["needs"] == "auth-check"
    assert review["if"] == "needs.auth-check.outputs.available == 'true'"


def test_review_installs_the_pinned_action_and_review_plugin() -> None:
    step = _review_step(_workflow()["jobs"]["review"])

    assert _PINNED_ACTION.match(step["uses"])
    assert "mattpocock-skills@claude-plugins-official" in step["with"]["plugins"]


def test_critical_findings_fail_the_check_via_structured_output() -> None:
    review = _workflow()["jobs"]["review"]
    claude_args = _review_step(review)["with"]["claude_args"]

    assert "--json-schema" in claude_args
    assert "critical_count" in claude_args

    verdict = review["steps"][-1]
    assert verdict["env"] == {"STRUCTURED_OUTPUT": "${{ steps.review.outputs.structured_output }}"}
    assert "critical" in verdict["run"]
    assert "exit 1" in verdict["run"]


def test_review_cannot_push_to_the_pr_branch() -> None:
    workflow = _workflow()

    assert workflow["permissions"] == {
        "contents": "read",
        "pull-requests": "write",
        "issues": "read",
    }
    for job in workflow["jobs"].values():
        assert "permissions" not in job

    # OIDC 経由の Claude App トークン(contents: write を持ちうる)ではなく、
    # workflow スコープの GITHUB_TOKEN で動かすことを固定する
    step = _review_step(workflow["jobs"]["review"])
    assert step["with"]["github_token"] == "${{ secrets.GITHUB_TOKEN }}"
