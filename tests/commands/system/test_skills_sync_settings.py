from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system import skills_sync


def _template(root: Path) -> None:
    claude = root / ".claude"
    claude.mkdir()
    (claude / "settings.template.json").write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Agent", "Bash(uv run yt-upload-auto*)"], "deny": ["Read(.env)"]},
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Edit|Write",
                            "hooks": [{"type": "command", "command": "block-secrets"}],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


def _run(root: Path, target: Path, monkeypatch, *extra: str) -> int:
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: root)
    return skills_sync.main(["sync", "--asset", "settings", "--target", str(target), *extra])


def _workspace_guard_command(settings: dict[str, object]) -> str:
    groups = settings["hooks"]["PreToolUse"]
    commands = [
        hook["command"]
        for group in groups
        if group["matcher"] == "Edit|Write"
        for hook in group["hooks"]
        if "yt-workspace-guard" in hook["command"]
    ]
    assert len(commands) == 1
    return commands[0]


def _session_context_command(settings: dict[str, object]) -> str:
    groups = settings["hooks"]["SessionStart"]
    commands = [hook["command"] for group in groups for hook in group["hooks"]]
    assert commands == ["uv run yt-workspace-guard context"]
    return commands[0]


# repo 自身の settings.json は nix devShell が構築した .venv を hook が作り直さない
# よう --no-sync を付ける（#4605）。下流配布 template は uv が venv を管理するため
# 従来どおり sync あり。
_PROGRESS_HOOK_COMMANDS = (
    "uv run yt-progress-hook",
    "uv run --no-sync yt-progress-hook",
)


def _progress_hook_matchers(settings: dict[str, object], event: str) -> list[str]:
    groups = settings["hooks"][event]
    return [
        group["matcher"]
        for group in groups
        if any(hook["command"] in _PROGRESS_HOOK_COMMANDS for hook in group["hooks"])
    ]


def test_settings_merge_preserves_local_values_and_accepts_hooks(tmp_path, monkeypatch) -> None:
    _template(tmp_path)
    target = tmp_path / "downstream" / ".claude" / "settings.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(
            {
                "env": {"LOCAL": "1"},
                "permissions": {"allow": ["LocalRule"], "deny": []},
                "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "local"}]}]},
            }
        ),
        encoding="utf-8",
    )

    assert _run(tmp_path, target, monkeypatch, "--accept-hooks") == 0
    merged = json.loads(target.read_text(encoding="utf-8"))
    assert merged["env"] == {"LOCAL": "1"}
    assert merged["permissions"]["allow"] == ["LocalRule", "Agent", "Bash(uv run yt-upload-auto*)"]
    assert merged["permissions"]["deny"] == ["Read(.env)"]
    assert len(merged["hooks"]["PreToolUse"]) == 2

    before = target.read_bytes()
    assert _run(tmp_path, target, monkeypatch, "--accept-hooks") == 0
    assert target.read_bytes() == before


def test_settings_noninteractive_skips_hooks_but_merges_permissions(tmp_path, monkeypatch) -> None:
    _template(tmp_path)
    target = tmp_path / "settings.json"
    assert _run(tmp_path, target, monkeypatch) == 0
    merged = json.loads(target.read_text(encoding="utf-8"))
    assert merged["permissions"]["allow"]
    assert "hooks" not in merged


def test_distributed_settings_include_workspace_guard_alongside_auth_hook(tmp_path, monkeypatch) -> None:
    target = tmp_path / "downstream" / ".claude" / "settings.json"

    assert _run(REPO_ROOT, target, monkeypatch, "--accept-hooks") == 0

    merged = json.loads(target.read_text(encoding="utf-8"))
    command = _workspace_guard_command(merged)
    assert "uv run yt-workspace-guard check $CLAUDE_FILE_PATHS" in command
    all_commands = [hook["command"] for group in merged["hooks"]["PreToolUse"] for hook in group["hooks"]]
    assert any("auth/client_secrets.json" in candidate for candidate in all_commands)


def test_distributed_settings_include_session_start_context_hook(tmp_path, monkeypatch) -> None:
    target = tmp_path / "downstream" / ".claude" / "settings.json"

    assert _run(REPO_ROOT, target, monkeypatch, "--accept-hooks") == 0

    merged = json.loads(target.read_text(encoding="utf-8"))
    assert _session_context_command(merged) == "uv run yt-workspace-guard context"


def test_distributed_settings_include_background_progress_hook(tmp_path, monkeypatch) -> None:
    target = tmp_path / "downstream" / ".claude" / "settings.json"

    assert _run(REPO_ROOT, target, monkeypatch, "--accept-hooks") == 0

    merged = json.loads(target.read_text(encoding="utf-8"))
    assert _progress_hook_matchers(merged, "PreToolUse") == ["Bash|Task|Agent|Workflow"]
    assert _progress_hook_matchers(merged, "PostToolUse") == ["Bash|Task|Agent|Workflow"]


def test_repository_settings_include_background_progress_hook() -> None:
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))

    assert _progress_hook_matchers(settings, "PreToolUse") == ["Bash|Task|Agent|Workflow"]
    assert _progress_hook_matchers(settings, "PostToolUse") == ["Bash|Task|Agent|Workflow"]


def test_workspace_guard_hook_prefilters_unrelated_paths(tmp_path) -> None:
    settings = json.loads((REPO_ROOT / ".claude" / "settings.template.json").read_text(encoding="utf-8"))
    command = _workspace_guard_command(settings)
    env = {**os.environ, "CLAUDE_FILE_PATHS": "README.md docs/guide.md", "PATH": str(tmp_path)}

    result = subprocess.run(command, shell=True, env=env, capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert result.stderr == ""


def test_workspace_guard_hook_propagates_block_and_paths(tmp_path) -> None:
    settings = json.loads((REPO_ROOT / ".claude" / "settings.template.json").read_text(encoding="utf-8"))
    command = _workspace_guard_command(settings)
    invocation = tmp_path / "invocation"
    fake_uv = tmp_path / "uv"
    fake_uv.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" > "{invocation}"\necho "channel mismatch" >&2\nexit 2\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    paths = "channels/beta/collections/new workspace/assets/cover.png"
    env = {**os.environ, "CLAUDE_FILE_PATHS": paths, "PATH": str(tmp_path)}

    result = subprocess.run(command, shell=True, env=env, capture_output=True, text=True, check=False)

    assert result.returncode == 2
    assert result.stderr == "channel mismatch\n"
    assert invocation.read_text(encoding="utf-8") == f"run yt-workspace-guard check {paths}\n"


def test_settings_invalid_target_is_not_overwritten(tmp_path, monkeypatch) -> None:
    _template(tmp_path)
    target = tmp_path / "settings.json"
    target.write_text("{broken", encoding="utf-8")
    before = target.read_bytes()
    assert _run(tmp_path, target, monkeypatch, "--accept-hooks") == 1
    assert target.read_bytes() == before


@pytest.mark.parametrize("invalid_root", ["[]", "null", '"scalar"'])
def test_settings_non_object_root_is_rejected_without_overwrite(tmp_path, monkeypatch, invalid_root: str) -> None:
    _template(tmp_path)
    target = tmp_path / "settings.json"
    target.write_text(invalid_root, encoding="utf-8")
    before = target.read_bytes()

    assert _run(tmp_path, target, monkeypatch, "--accept-hooks") == 1

    assert target.read_bytes() == before


def test_dev_only_skills_are_listed_but_not_distributed(tmp_path, monkeypatch, capsys) -> None:
    skills = tmp_path / ".claude" / "skills"
    for name in ("normal", "automation-release", "shadcn"):
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: tmp_path)

    assert skills_sync.bundled_skill_names() == ["normal"]
    assert skills_sync.main(["list", "--asset", "skills"]) == 0
    output = capsys.readouterr().out
    assert "automation-release (開発専用・downstream 配布対象外)" in output
    assert "shadcn (開発専用・downstream 配布対象外)" in output
