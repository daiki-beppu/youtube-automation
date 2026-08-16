"""Claude Code の長時間処理の開始・完了時に進捗を表示する hook。"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TextIO

from youtube_automation.commands.system.progress_hook.workflow_state import STAGES as _STAGES
from youtube_automation.commands.system.progress_hook.workflow_state import load_progress_snapshot

_STAGE_COMMANDS = {
    "音源生成": (
        "yt-generate-lyria-master",
        "yt-generate-minimax-master",
        "yt-generate-suno",
        "yt-suno-unattended-request",
    ),
    "マスター化": ("yt-generate-master", "yt-finalize-master"),
    "動画化": ("yt-generate-videos-batch", "yt-generate-loop-video", "ffmpeg"),
    "サムネイル": ("yt-generate-image", "yt-thumbnail-text"),
    "アップロード": ("yt-upload-collection", "yt-upload-auto", "yt-upload-shorts"),
    "公開後処理": ("yt-pinned-comment", "yt-metadata-audit", "yt-comments-reply"),
    "分析": ("yt-analytics", "yt-benchmark-collect", "yt-benchmark-comments", "yt-video-analyze"),
}
_AGENT_TOOLS = frozenset({"Task", "Agent", "Workflow"})


@dataclass(frozen=True)
class _Invocation:
    event: str
    tool_name: str
    tool_input: Mapping[object, object]
    stage: str | None
    command_name: str | None
    cwd: str | None


def _nonempty_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _classify_command(command: str | None) -> tuple[str | None, str | None]:
    if command is None:
        return None, None
    for stage, command_names in _STAGE_COMMANDS.items():
        for command_name in command_names:
            if re.search(rf"(?<![\w-]){re.escape(command_name)}(?![\w-])", command):
                return stage, command_name
    return None, None


def _parse_invocation(payload: object) -> _Invocation | None:
    if not isinstance(payload, Mapping):
        return None
    tool_name = _nonempty_string(payload.get("tool_name"))
    tool_input = payload.get("tool_input")
    if tool_name is None or not isinstance(tool_input, Mapping):
        return None
    event = _nonempty_string(payload.get("hook_event_name")) or "PreToolUse"
    command = _nonempty_string(tool_input.get("command"))
    stage, command_name = _classify_command(command)
    cwd = _nonempty_string(payload.get("cwd"))
    return _Invocation(event, tool_name, tool_input, stage, command_name, cwd)


def _should_display(invocation: _Invocation) -> bool:
    if invocation.event not in {"PreToolUse", "PostToolUse"}:
        return False
    if invocation.tool_name in _AGENT_TOOLS:
        return True
    if invocation.tool_name != "Bash":
        return False
    return invocation.stage is not None or invocation.tool_input.get("run_in_background") is True


def _first_command_token(command: str | None) -> str:
    if command is None:
        return "Bash"
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    return tokens[0] if tokens else "Bash"


def _unclassified_detail(invocation: _Invocation) -> str:
    command = _nonempty_string(invocation.tool_input.get("command"))
    subagent_type = _nonempty_string(invocation.tool_input.get("subagent_type"))
    if invocation.tool_name == "Bash":
        kind = _first_command_token(command)
    else:
        kind = subagent_type or invocation.tool_name
    description = _nonempty_string(invocation.tool_input.get("description"))
    return f"{kind} — {description}" if description is not None else kind


def _render(invocation: _Invocation) -> str:
    completed = invocation.event == "PostToolUse"
    command = _nonempty_string(invocation.tool_input.get("command"))
    snapshot = load_progress_snapshot(invocation.cwd, command)
    lines = ["```"]
    if invocation.stage is None:
        for index, stage in enumerate(_STAGES):
            marker = (
                "✓"
                if (snapshot is not None and stage in snapshot.completed_stages) or (snapshot is None and index <= 2)
                else "○"
            )
            lines.append(f"  {marker}  {stage}")
        lines.append(f"  ⋯  {_unclassified_detail(invocation)}")
    else:
        current_index = _STAGES.index(invocation.stage)
        for index, stage in enumerate(_STAGES):
            if snapshot is not None and not completed and index == current_index:
                marker = "▸"
            elif snapshot is not None:
                marker = "✓" if stage in snapshot.completed_stages else "○"
            elif index < current_index or (completed and index == current_index):
                marker = "✓"
            elif index == current_index:
                marker = "▸"
            else:
                marker = "○"
            detail = f" — {invocation.command_name}" if index == current_index else ""
            lines.append(f"  {marker}  {stage}{detail}")
    lines.append("```")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """hook payload を読み、表示対象の処理に進捗図を返す。"""

    parser = argparse.ArgumentParser(description="長時間処理の進捗図を claude.app へ表示する")
    parser.parse_args(argv)
    source = stdin if stdin is not None else sys.stdin
    try:
        payload = json.load(source)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0

    invocation = _parse_invocation(payload)
    if invocation is not None and _should_display(invocation):
        print(json.dumps({"systemMessage": _render(invocation)}, ensure_ascii=False))
    return 0
