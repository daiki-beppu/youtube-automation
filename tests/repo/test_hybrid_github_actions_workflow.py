"""Downstream hybrid GitHub Actions workflow distribution contract (#4054)."""

from __future__ import annotations

import re

import yaml

from tests.helpers.paths import REPO_ROOT

_WORKFLOW = REPO_ROOT / "src/youtube_automation/infrastructure/resources/channel/youtube-automation.yml"


def _document() -> dict[str, object]:
    document = yaml.load(_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def test_workflow_stays_unscheduled_until_configured_and_serializes_runs_without_cancelling() -> None:
    document = _document()
    assert document["on"] in (None, "")

    concurrency = document["concurrency"]
    assert isinstance(concurrency, dict)
    assert concurrency == {
        "group": "youtube-automation-${{ github.repository }}",
        "cancel-in-progress": "false",
    }


def test_workflow_is_a_thin_platform_wrapper_for_sandwich_script() -> None:
    document = _document()
    jobs = document["jobs"]
    assert isinstance(jobs, dict) and list(jobs) == ["automation"]
    job = jobs["automation"]
    assert isinstance(job, dict)
    steps = job["steps"]
    assert isinstance(steps, list)

    shell_steps = [step for step in steps if isinstance(step, dict) and "run" in step]
    assert len(shell_steps) == 1
    command = shell_steps[0]["run"]
    assert isinstance(command, str)
    assert command.count("run-sandwich.sh") == 1
    assert "uv run" not in command
    assert not re.search(r"\b(if|for|while|case|ffmpeg|yt-workflow-state)\b", command)

    env = shell_steps[0]["env"]
    assert isinstance(env, dict)
    assert {
        key: env[key]
        for key in (
            "CLAUDE_CODE_OAUTH_TOKEN",
            "R2_ACCESS_KEY_ID",
            "R2_ACCOUNT_ID",
            "R2_API_TOKEN",
            "R2_BUCKET",
        )
    } == {
        "CLAUDE_CODE_OAUTH_TOKEN": "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}",
        "R2_ACCESS_KEY_ID": "${{ secrets.R2_ACCESS_KEY_ID }}",
        "R2_ACCOUNT_ID": "${{ secrets.R2_ACCOUNT_ID }}",
        "R2_API_TOKEN": "${{ secrets.R2_API_TOKEN }}",
        "R2_BUCKET": "${{ vars.R2_BUCKET }}",
    }
    assert {
        key: env[key]
        for key in (
            "YTA_CHANNEL_SLUG",
            "YTA_COLLECTION",
            "YTA_COLLECTION_DIR",
            "YTA_AGENT",
            "YTA_AUTOMATION_PROMPT",
        )
    } == {
        "YTA_CHANNEL_SLUG": "${{ vars.YTA_CHANNEL_SLUG }}",
        "YTA_COLLECTION": "${{ vars.YTA_COLLECTION }}",
        "YTA_COLLECTION_DIR": "${{ vars.YTA_COLLECTION_DIR }}",
        "YTA_AGENT": "${{ vars.YTA_AGENT }}",
        "YTA_AUTOMATION_PROMPT": "${{ vars.YTA_AUTOMATION_PROMPT }}",
    }


def test_workflow_actions_are_immutable_pins() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    uses = re.findall(r"^\s*- uses: ([^\s]+)\s+#\s+(\S+)\s*$", text, re.MULTILINE)
    assert uses == [
        ("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
        ("astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9", "v9.0.0"),
    ]
