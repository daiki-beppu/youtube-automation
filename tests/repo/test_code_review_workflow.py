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
    assert "report_markdown" in claude_args

    verdict = review["steps"][-1]
    assert verdict["env"] == {
        "STRUCTURED_OUTPUT": "${{ steps.review.outputs.structured_output }}",
        "SKIPPED": "${{ steps.previous.outputs.skip }}",
        "PREV_CRIT": "${{ steps.previous.outputs.prev_crit }}",
    }
    assert "critical" in verdict["run"]
    assert "exit 1" in verdict["run"]


def _allowed_tools(claude_args: str) -> list[str]:
    line = next(part for part in claude_args.splitlines() if part.startswith("--allowedTools"))
    return line.removeprefix("--allowedTools").strip().strip('"').split(",")


def test_review_comment_is_upserted_by_a_workflow_step_not_by_claude() -> None:
    review = _workflow()["jobs"]["review"]
    steps = review["steps"]

    # Claude にはコメント投稿系コマンドを許可しない(投稿経路は workflow step に一本化)
    tools = _allowed_tools(_review_step(review)["with"]["claude_args"])
    assert not [tool for tool in tools if tool.startswith("Bash(gh pr comment")]
    assert not [tool for tool in tools if tool.startswith("Bash(gh api")]

    post = next(step for step in steps if step.get("name") == "Post review comment")
    assert post["if"] == ("steps.previous.outputs.skip != 'true' && steps.review.outputs.structured_output != ''")
    assert post["env"]["STRUCTURED_OUTPUT"] == "${{ steps.review.outputs.structured_output }}"
    script = post["run"]
    # marker は job env の 1 箇所定義（ci-autofix の startswith gate と揃える契約）
    assert review["env"]["REVIEW_MARKER"] == "<!-- code-review-workflow -->"
    assert 'echo "$REVIEW_MARKER"' in script
    assert "report_markdown" in script
    assert "PATCH" in script

    # コメント一覧の取得は Look up previous review の 1 回だけ（id を再利用し再取得しない）
    assert post["env"]["COMMENT_ID"] == "${{ steps.previous.outputs.comment_id }}"
    assert "--paginate" not in script

    # critical 判定で fail する前に、指摘本文が必ず PR へ投稿される
    assert steps.index(post) < steps.index(steps[-1])
    assert steps[-1]["run"].find("exit 1") != -1


def test_unchanged_diff_skips_the_paid_review_but_reapplies_the_verdict() -> None:
    review = _workflow()["jobs"]["review"]
    steps = review["steps"]

    fingerprint = next(step for step in steps if step.get("id") == "fingerprint")
    assert "git patch-id --stable" in fingerprint["run"]

    previous = next(step for step in steps if step.get("id") == "previous")
    # メタ行の語彙は crit= 固定(ci-autofix の severity パーサに "critical" を誤検出させない)
    assert "code-review-meta patch=" in previous["run"]
    assert "crit=" in previous["run"]
    assert "critical" not in previous["run"].split("code-review-meta")[1].splitlines()[0]
    # comment_id も同じ 1 回の取得で拾い、Post review comment 側の再取得を不要にする
    assert "comment_id=" in previous["run"]
    assert previous["run"].count("gh api") == 1

    assert _review_step(review)["if"] == "steps.previous.outputs.skip != 'true'"

    verdict = steps[-1]
    assert verdict["env"]["SKIPPED"] == "${{ steps.previous.outputs.skip }}"
    assert verdict["env"]["PREV_CRIT"] == "${{ steps.previous.outputs.prev_crit }}"
    assert "exit 1" in verdict["run"]


def test_review_meta_line_never_matches_the_autofix_severity_parser() -> None:
    """メタ行が ci-autofix の severity_count に数値として拾われないことの回帰ガード。"""
    import subprocess

    meta_line = "<!-- code-review-meta patch=0123abcd crit=3 -->"
    result = subprocess.run(
        ["bash", "-c", "grep -ioE 'critical[[:space:][:punct:]]*[0-9]+' || true"],
        input=meta_line,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""


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
