"""Downstream hybrid GitHub Actions workflow distribution contract (#4054)."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml

from tests.helpers.paths import REPO_ROOT

_WORKFLOW = REPO_ROOT / "src/youtube_automation/infrastructure/resources/channel/youtube-automation.yml"


def _document() -> dict[str, object]:
    document = yaml.load(_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def test_workflow_stays_unscheduled_but_allows_manual_auth_verification() -> None:
    document = _document()
    assert document["on"] == {"workflow_dispatch": ""}


def test_workflow_serializes_runs_without_cancelling() -> None:
    document = _document()

    concurrency = document["concurrency"]
    assert isinstance(concurrency, dict)
    assert concurrency == {
        "group": "youtube-automation-${{ github.repository }}",
        "cancel-in-progress": "false",
    }


def test_workflow_bootstraps_authenticated_claude_runner_before_sandwich_script() -> None:
    document = _document()
    jobs = document["jobs"]
    assert isinstance(jobs, dict) and list(jobs) == ["automation"]
    job = jobs["automation"]
    assert isinstance(job, dict)
    assert job["env"] == {"GH_TOKEN": "${{ github.token }}"}
    steps = job["steps"]
    assert isinstance(steps, list)

    named_steps = {step["name"]: step for step in steps if isinstance(step, dict) and isinstance(step.get("name"), str)}
    authentication = named_steps["Configure private repository authentication"]
    assert authentication["run"] == "gh auth setup-git"

    install = named_steps["Install Claude Code headless runner"]
    install_command = install["run"]
    assert isinstance(install_command, str)
    assert "https://claude.ai/install.sh" in install_command
    assert "claude-native" in install_command
    assert ".claude/skills/wf-new/references/claude-headless.sh" in install_command
    assert "GITHUB_PATH" in install_command

    runner_step = named_steps["Run platform-neutral sandwich runner"]
    step_names = [step.get("name") for step in steps if isinstance(step, dict)]
    assert (
        step_names.index(authentication["name"])
        < step_names.index(install["name"])
        < step_names.index(runner_step["name"])
    )
    command = runner_step["run"]
    assert isinstance(command, str)
    assert command.count("run-github-actions.sh") == 1
    assert "uv run" not in command
    assert not re.search(r"\b(if|for|while|case|ffmpeg|yt-workflow-state)\b", command)

    env = runner_step["env"]
    assert isinstance(env, dict)
    assert {
        key: env[key]
        for key in (
            "CLAUDE_CODE_OAUTH_TOKEN",
            "YOUTUBE_OAUTH_TOKEN_JSON",
            "DISCORD_WEBHOOK_URL",
            "R2_ACCESS_KEY_ID",
            "R2_ACCOUNT_ID",
            "R2_API_TOKEN",
            "R2_BUCKET",
        )
    } == {
        "CLAUDE_CODE_OAUTH_TOKEN": "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}",
        "YOUTUBE_OAUTH_TOKEN_JSON": "${{ secrets.YOUTUBE_OAUTH_TOKEN_JSON }}",
        "DISCORD_WEBHOOK_URL": "${{ secrets.DISCORD_WEBHOOK_URL }}",
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
            "YTA_STAGE",
            "YTA_AUTOMATION_PROMPT",
        )
    } == {
        "YTA_CHANNEL_SLUG": "${{ vars.YTA_CHANNEL_SLUG }}",
        "YTA_COLLECTION": "${{ vars.YTA_COLLECTION }}",
        "YTA_COLLECTION_DIR": "${{ vars.YTA_COLLECTION_DIR }}",
        "YTA_AGENT": "${{ vars.YTA_AGENT }}",
        "YTA_STAGE": "${{ vars.YTA_STAGE || 'planning' }}",
        "YTA_AUTOMATION_PROMPT": "${{ vars.YTA_AUTOMATION_PROMPT || '/wf-new --auto' }}",
    }
    command = runner_step["run"]
    assert '--stage "$YTA_STAGE"' in command

    diagnostics = named_steps["Report Claude Code failure log"]
    assert diagnostics["if"] == "${{ failure() }}"
    assert "claude-output.log" in diagnostics["run"]


def test_workflow_actions_are_immutable_pins() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    uses = re.findall(r"^\s*- uses: ([^\s]+)\s+#\s+(\S+)\s*$", text, re.MULTILINE)
    assert uses == [
        ("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
        ("astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9", "v9.0.0"),
    ]


def test_claude_headless_wrapper_adds_permission_flag_and_captures_output(tmp_path: Path) -> None:
    wrapper = REPO_ROOT / ".claude/skills/wf-new/references/claude-headless.sh"
    installed = tmp_path / wrapper.name
    installed.write_bytes(wrapper.read_bytes())
    installed.chmod(0o755)
    native = tmp_path / "claude-native"
    native.write_text('#!/bin/sh\nprintf "%s\\n" "$*"\nprintf "agent output\\n"\n', encoding="utf-8")
    native.chmod(0o755)

    result = subprocess.run(
        [str(installed), "--print", "hello"],
        text=True,
        capture_output=True,
        env={**os.environ, "RUNNER_TEMP": str(tmp_path)},
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "--dangerously-skip-permissions --print hello\nagent output\n"
    assert (tmp_path / "claude-output.log").read_text(encoding="utf-8") == result.stdout


def test_claude_headless_wrapper_preserves_native_failure_status(tmp_path: Path) -> None:
    wrapper = REPO_ROOT / ".claude/skills/wf-new/references/claude-headless.sh"
    installed = tmp_path / wrapper.name
    installed.write_bytes(wrapper.read_bytes())
    installed.chmod(0o755)
    native = tmp_path / "claude-native"
    native.write_text('#!/bin/sh\nprintf "agent failed\\n"\nexit 23\n', encoding="utf-8")
    native.chmod(0o755)

    result = subprocess.run(
        [str(installed)],
        text=True,
        capture_output=True,
        env={**os.environ, "RUNNER_TEMP": str(tmp_path)},
        check=False,
    )

    assert result.returncode == 23
    assert (tmp_path / "claude-output.log").read_text(encoding="utf-8") == "agent failed\n"


def _run_auth_wrapper(
    tmp_path: Path,
    *,
    agent: str,
    token: str | None,
    runner_exit: int,
) -> tuple[subprocess.CompletedProcess[str], str, Path]:
    references = tmp_path / "references"
    references.mkdir()
    wrapper = REPO_ROOT / ".claude/skills/wf-new/references/run-github-actions.sh"
    installed = references / wrapper.name
    installed.write_bytes(wrapper.read_bytes())
    installed.chmod(0o755)

    calls = tmp_path / "calls"
    runner = references / "run-sandwich.sh"
    runner.write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" > "{calls}"\nexit {runner_exit}\n',
        encoding="utf-8",
    )
    runner.chmod(0o755)
    summary = tmp_path / "summary.md"
    env = {
        **os.environ,
        "GITHUB_STEP_SUMMARY": str(summary),
        "YTA_AGENT": agent,
    }
    if token is not None:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    else:
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
    result = subprocess.run(
        [str(installed), "--repository-url", "https://example.invalid/channel.git"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    summary_text = summary.read_text(encoding="utf-8") if summary.exists() else ""
    return result, summary_text, calls


def test_github_actions_wrapper_refuses_missing_claude_token_before_runner(tmp_path: Path) -> None:
    result, summary, calls = _run_auth_wrapper(
        tmp_path,
        agent="claude",
        token=None,
        runner_exit=0,
    )

    assert result.returncode != 0
    assert not calls.exists()
    assert "CLAUDE_CODE_OAUTH_TOKEN" in summary
    assert "rotation" in summary


def test_github_actions_wrapper_passes_validated_inputs_to_runner(tmp_path: Path) -> None:
    token = "oauth-secret-must-not-be-rendered"
    result, summary, calls = _run_auth_wrapper(
        tmp_path,
        agent="claude",
        token=token,
        runner_exit=0,
    )

    assert result.returncode == 0
    assert calls.read_text(encoding="utf-8").strip() == ("--repository-url https://example.invalid/channel.git")
    assert token not in result.stdout + result.stderr + summary


def test_github_actions_wrapper_keeps_agent_failure_nonzero_and_reports_rotation(tmp_path: Path) -> None:
    token = "expired-oauth-secret-must-not-be-rendered"
    result, summary, calls = _run_auth_wrapper(
        tmp_path,
        agent="claude",
        token=token,
        runner_exit=23,
    )

    assert result.returncode == 23
    assert calls.exists()
    assert "rotation" in summary
    assert token not in result.stdout + result.stderr + summary
