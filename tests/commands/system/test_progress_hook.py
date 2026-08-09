from __future__ import annotations

import io
import json

import pytest

from youtube_automation.commands.system import progress_hook


def _run(payload: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    exit_code = progress_hook.main([], stdin=io.StringIO(payload))
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_should_emit_progress_system_message_when_background_bash_starts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"run_in_background": True}})

    exit_code, stdout, stderr = _run(payload, capsys)

    assert exit_code == 0
    message = json.loads(stdout)["systemMessage"]
    assert "▸" not in message
    assert "  ⋯  Bash" in message
    assert stderr == ""


def test_should_emit_nothing_when_foreground_bash_starts(capsys: pytest.CaptureFixture[str]) -> None:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {}})

    exit_code, stdout, stderr = _run(payload, capsys)

    assert exit_code == 0
    assert stdout == ""
    assert stderr == ""


@pytest.mark.parametrize(
    ("command", "stage"),
    [
        ("uv run yt-generate-lyria-master", "音源生成"),
        ("uv run yt-generate-suno", "音源生成"),
        ("uv run yt-suno-unattended-request", "音源生成"),
        ("uv run yt-generate-master", "マスター化"),
        ("uv run yt-finalize-master", "マスター化"),
        ("uv run yt-generate-videos-batch", "動画化"),
        ("uv run yt-generate-loop-video", "動画化"),
        ("ffmpeg -i input.mp3 output.mp4", "動画化"),
        ("uv run yt-generate-image", "サムネイル"),
        ("uv run yt-thumbnail-text", "サムネイル"),
        ("uv run yt-upload-collection", "アップロード"),
        ("uv run yt-upload-auto", "アップロード"),
        ("uv run yt-upload-shorts", "アップロード"),
        ("uv run yt-pinned-comment", "公開後処理"),
        ("uv run yt-metadata-audit", "公開後処理"),
        ("uv run yt-comments-reply", "公開後処理"),
        ("uv run yt-analytics", "分析"),
        ("uv run yt-benchmark-collect", "分析"),
        ("uv run yt-benchmark-comments", "分析"),
        ("uv run yt-video-analyze", "分析"),
    ],
)
def test_should_mark_classified_stage_for_long_foreground_command(
    command: str,
    stage: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}})

    exit_code, stdout, stderr = _run(payload, capsys)

    message = json.loads(stdout)["systemMessage"]
    assert exit_code == 0
    assert f"  ▸  {stage} — {command.split()[2] if command.startswith('uv run ') else command.split()[0]}" in message
    assert message.count("▸") == 1
    assert stderr == ""


def test_should_emit_unclassified_agent_work_with_description(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "Explore", "description": "hook 定義箇所を調査"},
        }
    )

    exit_code, stdout, stderr = _run(payload, capsys)

    message = json.loads(stdout)["systemMessage"]
    assert exit_code == 0
    assert "▸" not in message
    assert "  ⋯  Explore — hook 定義箇所を調査" in message
    assert stderr == ""


@pytest.mark.parametrize(
    ("tool_name", "tool_input", "expected"),
    [
        ("Task", {"subagent_type": "general-purpose"}, "general-purpose"),
        ("Workflow", {}, "Workflow"),
        ("Bash", {"run_in_background": True, "command": "gh pr checks 42"}, "gh"),
    ],
)
def test_should_use_nonempty_fallback_for_unclassified_work(
    tool_name: str,
    tool_input: dict[str, object],
    expected: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": tool_input})

    exit_code, stdout, stderr = _run(payload, capsys)

    message = json.loads(stdout)["systemMessage"]
    assert exit_code == 0
    assert f"  ⋯  {expected}" in message
    assert stderr == ""


def test_should_mark_classified_stage_complete_after_displayed_command_returns(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ffmpeg -i input.mp3 output.mp4"},
        }
    )

    exit_code, stdout, stderr = _run(payload, capsys)

    message = json.loads(stdout)["systemMessage"]
    assert exit_code == 0
    assert "  ✓  動画化 — ffmpeg" in message
    assert "▸" not in message
    assert stderr == ""


def test_should_emit_nothing_after_unclassified_foreground_command_returns(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}})

    exit_code, stdout, stderr = _run(payload, capsys)

    assert exit_code == 0
    assert stdout == ""
    assert stderr == ""


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        json.dumps({"tool_name": "Bash", "tool_input": []}),
        json.dumps({"tool_name": "Bash", "tool_input": {"run_in_background": "true"}}),
    ],
)
def test_should_emit_nothing_when_payload_is_invalid_or_unsupported(
    payload: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code, stdout, stderr = _run(payload, capsys)

    assert exit_code == 0
    assert stdout == ""
    assert stderr == ""
