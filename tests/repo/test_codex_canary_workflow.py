"""Monthly Codex escape canary distribution contract (#4060)."""

from __future__ import annotations

import re

import yaml

from tests.helpers.paths import REPO_ROOT

_WORKFLOW = REPO_ROOT / "src/youtube_automation/infrastructure/resources/channel/codex-canary.yml"


def _document() -> dict[str, object]:
    document = yaml.load(_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def test_canary_has_fixed_monthly_schedule_and_manual_control() -> None:
    document = _document()
    assert document["on"] == {
        "schedule": [{"cron": "17 3 1 * *"}],
        "workflow_dispatch": "",
    }


def test_canary_runs_pinned_official_action_with_narrow_permissions() -> None:
    document = _document()
    assert document["permissions"] == {"contents": "read"}
    jobs = document["jobs"]
    assert isinstance(jobs, dict)
    canary = jobs["codex-canary"]
    assert isinstance(canary, dict)
    steps = canary["steps"]
    assert isinstance(steps, list)

    action_step = next(step for step in steps if isinstance(step, dict) and step.get("id") == "codex")
    assert action_step["uses"] == "openai/codex-action@52fe01ec70a42f454c9d2ebd47598f9fd6893d56"
    assert action_step["with"] == {
        "openai-api-key": "${{ secrets.OPENAI_API_KEY }}",
        "permission-profile": ":read-only",
        "allow-bots": "true",
        "allow-bot-users": "github-actions",
        "prompt": "Reply with exactly CODEX_ESCAPE_CANARY_OK. Do not inspect or modify repository files.",
    }
    assert steps[-1] is action_step

    text = _WORKFLOW.read_text(encoding="utf-8")
    uses = re.findall(r"^\s+(?:- )?uses: ([^\s]+)\s+#\s+(\S+)\s*$", text, re.MULTILINE)
    assert uses == [
        ("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
        ("openai/codex-action@52fe01ec70a42f454c9d2ebd47598f9fd6893d56", "v1"),
        ("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
        ("astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9", "v9.0.0"),
    ]


def test_canary_reports_success_or_failure_through_typed_notification_cli() -> None:
    document = _document()
    jobs = document["jobs"]
    assert isinstance(jobs, dict)
    notify = jobs["notify"]
    assert isinstance(notify, dict)
    assert notify["needs"] == "codex-canary"
    assert notify["if"] == "${{ always() }}"

    steps = notify["steps"]
    assert isinstance(steps, list)
    shell_steps = [step for step in steps if isinstance(step, dict) and "run" in step]
    assert len(shell_steps) == 1
    step = shell_steps[0]
    assert step["env"] == {
        "DISCORD_WEBHOOK_URL": "${{ secrets.DISCORD_WEBHOOK_URL }}",
        "YTA_CANARY_RESULT": "${{ needs.codex-canary.result }}",
        "YTA_CHANNEL_SLUG": "${{ vars.YTA_CHANNEL_SLUG }}",
    }
    command = step["run"]
    assert command == (
        "uv run --frozen yt-codex-canary-notify "
        '--result "$YTA_CANARY_RESULT" --channel "${YTA_CHANNEL_SLUG:-unknown-channel}"'
    )
