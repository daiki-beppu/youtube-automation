from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system import skills_sync
from youtube_automation.commands.system.skills_sync import _settings


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


# hook は呼び出し元の cwd に依存しないよう Claude の project root を明示する（#4835）。
# repo 自身の settings.json は nix devShell が構築した .venv を hook が作り直さない
# よう --no-sync も付ける（#4605）。下流配布 template は uv が venv を管理するため
# sync あり。両者を取り違えないよう、期待コマンドは呼び出し側が明示する。
_DISTRIBUTED_PROGRESS_HOOK_COMMAND = 'uv run --project "$CLAUDE_PROJECT_DIR" yt-progress-hook'
_REPOSITORY_PROGRESS_HOOK_COMMAND = 'uv run --no-sync --project "$CLAUDE_PROJECT_DIR" yt-progress-hook'


def _progress_hook_matchers(settings: dict[str, object], event: str, command: str) -> list[str]:
    groups = settings["hooks"][event]
    return [group["matcher"] for group in groups for hook in group["hooks"] if hook["command"] == command]


def _ruff_hook_command(settings: dict[str, object]) -> str:
    groups = settings["hooks"]["PostToolUse"]
    commands = [
        hook["command"]
        for group in groups
        if group["matcher"] == "Edit|Write|NotebookEdit"
        for hook in group["hooks"]
        if "ruff" in hook["command"]
    ]
    assert len(commands) == 1
    return commands[0]


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


def test_settings_prunes_known_removed_hooks_and_preserves_other_hooks(tmp_path, monkeypatch) -> None:
    _template(tmp_path)
    target = tmp_path / "settings.json"
    target.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Edit|Write",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": next(
                                        command
                                        for command in _settings._KNOWN_REMOVED_HOOK_COMMANDS
                                        if " check " in command
                                    ),
                                },
                                {"type": "command", "command": "keep-pre"},
                            ],
                        }
                    ],
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "uv run yt-workspace-guard context"}]},
                        {"hooks": [{"type": "command", "command": "keep-session"}]},
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    assert _run(tmp_path, target, monkeypatch, "--accept-hooks") == 0
    merged = json.loads(target.read_text(encoding="utf-8"))
    commands = [hook["command"] for groups in merged["hooks"].values() for group in groups for hook in group["hooks"]]
    assert set(commands) == {"keep-pre", "keep-session", "block-secrets"}
    assert all(group["hooks"] for groups in merged["hooks"].values() for group in groups)


def test_settings_noninteractive_reports_prune_without_writing(tmp_path, monkeypatch, capsys) -> None:
    _template(tmp_path)
    target = tmp_path / "settings.json"
    target.write_text(
        json.dumps(
            {
                "permissions": {
                    "allow": ["Agent", "Bash(uv run yt-upload-auto*)"],
                    "deny": ["Read(.env)"],
                },
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Edit|Write",
                            "hooks": [{"type": "command", "command": "block-secrets"}],
                        }
                    ],
                    "SessionStart": [{"hooks": [{"type": "command", "command": "uv run yt-workspace-guard context"}]}],
                },
            }
        ),
        encoding="utf-8",
    )
    before = target.read_bytes()

    assert _run(tmp_path, target, monkeypatch) == 0
    assert target.read_bytes() == before
    assert "hook 除去候補" in capsys.readouterr().out


def test_distributed_settings_template_excludes_workspace_guard() -> None:
    assert "yt-workspace-guard" not in (REPO_ROOT / ".claude/settings.template.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("settings_file", ["settings.template.json", "settings.json"])
def test_distributed_settings_template_includes_session_update(settings_file: str) -> None:
    settings = json.loads((REPO_ROOT / ".claude" / settings_file).read_text(encoding="utf-8"))
    hooks = settings["hooks"]["SessionStart"]
    assert hooks == [{"hooks": [{"type": "command", "command": "uv run yt-session-start", "timeout": 120}]}]


def test_distributed_settings_include_background_progress_hook(tmp_path, monkeypatch) -> None:
    target = tmp_path / "downstream" / ".claude" / "settings.json"

    assert _run(REPO_ROOT, target, monkeypatch, "--accept-hooks") == 0

    merged = json.loads(target.read_text(encoding="utf-8"))
    command = _DISTRIBUTED_PROGRESS_HOOK_COMMAND
    assert _progress_hook_matchers(merged, "PreToolUse", command) == ["Bash|Task|Agent|Workflow"]
    assert _progress_hook_matchers(merged, "PostToolUse", command) == ["Bash|Task|Agent|Workflow"]


def test_distributed_progress_hook_uses_claude_project_outside_project_cwd(tmp_path) -> None:
    settings = json.loads((REPO_ROOT / ".claude" / "settings.template.json").read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for group in settings["hooks"]["PreToolUse"]
        for hook in group["hooks"]
        if "yt-progress-hook" in hook["command"]
    ]
    assert commands == [_DISTRIBUTED_PROGRESS_HOOK_COMMAND]
    invocation = tmp_path / "invocation"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" > "{invocation}"\n', encoding="utf-8")
    fake_uv.chmod(0o755)
    outside_project = tmp_path / "outside-project"
    outside_project.mkdir()
    env = {**os.environ, "CLAUDE_PROJECT_DIR": "/workspace/channel", "PATH": str(fake_bin)}

    result = subprocess.run(
        commands[0],
        shell=True,
        cwd=outside_project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert invocation.read_text(encoding="utf-8") == "run --project /workspace/channel yt-progress-hook\n"


def test_repository_settings_include_background_progress_hook() -> None:
    """repo 自身の hook は既存 .venv を作り直さないよう --no-sync 付きで発火する（#4605）。"""
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))

    command = _REPOSITORY_PROGRESS_HOOK_COMMAND
    assert _progress_hook_matchers(settings, "PreToolUse", command) == ["Bash|Task|Agent|Workflow"]
    assert _progress_hook_matchers(settings, "PostToolUse", command) == ["Bash|Task|Agent|Workflow"]
    assert _progress_hook_matchers(settings, "PreToolUse", _DISTRIBUTED_PROGRESS_HOOK_COMMAND) == []
    assert _progress_hook_matchers(settings, "PostToolUse", _DISTRIBUTED_PROGRESS_HOOK_COMMAND) == []


def test_repository_ruff_hook_never_syncs_the_venv() -> None:
    """Edit 後の ruff hook も .venv を同期しない（#4605）。"""
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))

    command = _ruff_hook_command(settings)
    assert "uv run --no-sync ruff format" in command
    assert "uv run --no-sync ruff check --fix" in command
    assert "uv run ruff" not in command


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
