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


@pytest.fixture
def guard_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "channel with spaces"
    monkeypatch.setattr(skills_sync, "_editable_root", lambda: REPO_ROOT)
    assert (
        skills_sync.main(
            ["sync", "--asset", "skills", "--only", "automation", "--target", str(project / ".claude/skills")]
        )
        == 0
    )
    assert _run(REPO_ROOT, project / ".claude/settings.json", monkeypatch, "--accept-hooks") == 0
    return project


def _run_edit_guard(
    tmp_path: Path, guard_project: Path, settings_file: str, payload: str
) -> subprocess.CompletedProcess[str]:
    settings_path = (
        guard_project / ".claude/settings.json"
        if settings_file == "settings.template.json"
        else REPO_ROOT / ".claude/settings.json"
    )
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    command = next(
        hook["command"]
        for group in settings["hooks"]["PreToolUse"]
        if group["matcher"] == "Edit|Write"
        for hook in group["hooks"]
    )
    return subprocess.run(
        command,
        shell=True,
        cwd=tmp_path,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "CLAUDE_PROJECT_DIR": str(guard_project)},
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize("settings_file", ["settings.template.json", "settings.json"])
@pytest.mark.parametrize("tool", ["Edit", "Write"])
@pytest.mark.parametrize("prefix", ["", "/tmp/channel/", "/tmp/channel with spaces/"])
@pytest.mark.parametrize("name", [".env", "auth/token.json", "auth/client_secrets.json"])
def test_edit_guard_blocks_standard_stdin(
    tmp_path: Path, guard_project: Path, settings_file: str, tool: str, prefix: str, name: str
) -> None:
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": {"file_path": prefix + name, "content": "dummy-secret-content"},
        }
    )
    result = _run_edit_guard(tmp_path, guard_project, settings_file, payload)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr
    assert "dummy-secret-content" not in result.stderr


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "{broken",
        "null",
        "{}",
        *[
            json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": tool_input})
            for tool_input in (None, {}, {"file_path": None}, {"file_path": ""})
        ],
    ],
)
def test_edit_guard_rejects_invalid_payload_without_echoing_input(
    tmp_path: Path, guard_project: Path, payload: str
) -> None:
    result = _run_edit_guard(tmp_path, guard_project, "settings.template.json", payload)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("settings_file", ["settings.template.json", "settings.json"])
@pytest.mark.parametrize("tool", ["Edit", "Write"])
@pytest.mark.parametrize(
    "name",
    ["README.md", "config/channel/meta.json", "/tmp/channel with spaces/auth/token.json.example", ".env.example"],
)
def test_edit_guard_allows_ordinary_files(
    tmp_path: Path, guard_project: Path, settings_file: str, tool: str, name: str
) -> None:
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"file_path": name}})
    result = _run_edit_guard(tmp_path, guard_project, settings_file, payload)
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""


@pytest.mark.parametrize("settings_file, expected", [("settings.template.json", 0), ("settings.json", 2)])
@pytest.mark.parametrize("name", ["/tmp/channel/uv.lock", "/tmp/channel/flake.lock"])
def test_edit_guard_preserves_repository_only_lock_protection(
    tmp_path: Path, guard_project: Path, settings_file: str, expected: int, name: str
) -> None:
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {"file_path": name}})
    result = _run_edit_guard(tmp_path, guard_project, settings_file, payload)
    assert result.returncode == expected


def test_settings_diff_and_dry_run_report_same_removed_hooks(tmp_path, monkeypatch, capsys) -> None:
    target = tmp_path / "settings.json"
    assert _run(REPO_ROOT, target, monkeypatch, "--accept-hooks") == 0
    current = json.loads(target.read_text(encoding="utf-8"))
    current["hooks"]["SessionStart"].append(
        {"hooks": [{"type": "command", "command": "uv run yt-workspace-guard context"}]}
    )
    target.write_text(json.dumps(current), encoding="utf-8")
    before = target.read_bytes()
    capsys.readouterr()

    assert skills_sync.main(["diff", "--asset", "settings", "--target", str(target)]) == 0
    diff_output = capsys.readouterr().out
    assert "hook 除去候補" in diff_output
    assert "差分なし" not in diff_output
    assert _run(REPO_ROOT, target, monkeypatch, "--dry-run", "--accept-hooks") == 0
    dry_run_output = capsys.readouterr().out
    assert [line for line in diff_output.splitlines() if "hook " in line] == [
        line for line in dry_run_output.splitlines() if "hook " in line
    ]
    assert target.read_bytes() == before


# 移行前の command は `_settings` の移行表を正本として引く（テスト側に再定義するとソースだけ
# 変更されたときにドリフトが黙って通る）。移行後の command は配布 template の実文字列と一致するか
# を検証したいので、上部の `_DISTRIBUTED_PROGRESS_HOOK_COMMAND` などを明示したまま使う。
_LEGACY_HOOK_COMMANDS = {new: old for old, new in _settings._KNOWN_REPLACED_HOOK_COMMANDS.items()}


def test_settings_upgrade_known_hooks_preserves_local_options(tmp_path, monkeypatch, capsys) -> None:
    target = tmp_path / "settings.json"
    current = json.loads((REPO_ROOT / ".claude/settings.template.json").read_text(encoding="utf-8"))
    expected_guard = dict(current["hooks"]["PreToolUse"][0]["hooks"][0])
    legacy_guard = _LEGACY_HOOK_COMMANDS[expected_guard["command"]]
    for event in ("PreToolUse", "PostToolUse"):
        for group in current["hooks"][event]:
            for hook in group["hooks"]:
                if "yt-progress-hook" in hook["command"]:
                    hook["command"] = _LEGACY_HOOK_COMMANDS[_DISTRIBUTED_PROGRESS_HOOK_COMMAND]
                    hook["timeout"] = 37
    current["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = legacy_guard
    local_hook = {"type": "command", "command": "uv run yt-progress-hook --local", "timeout": 71}
    current["hooks"]["PreToolUse"][0]["hooks"].append(local_hook)
    current["hooks"]["SessionStart"][0]["hooks"][0]["timeout"] = 83
    target.write_text(json.dumps(current), encoding="utf-8")
    before = target.read_bytes()

    assert _run(REPO_ROOT, target, monkeypatch) == 0
    assert target.read_bytes() == before
    capsys.readouterr()
    assert skills_sync.main(["diff", "--asset", "settings", "--target", str(target)]) == 0
    diff_output = capsys.readouterr().out
    assert _run(REPO_ROOT, target, monkeypatch, "--dry-run", "--accept-hooks") == 0
    dry_run_output = capsys.readouterr().out
    assert [line for line in diff_output.splitlines() if "hook " in line] == [
        line for line in dry_run_output.splitlines() if "hook " in line
    ]
    assert target.read_bytes() == before
    assert _run(REPO_ROOT, target, monkeypatch, "--accept-hooks") == 0
    merged = json.loads(target.read_text(encoding="utf-8"))
    for event in ("PreToolUse", "PostToolUse"):
        progress = [
            hook
            for group in merged["hooks"][event]
            for hook in group["hooks"]
            if "yt-progress-hook" in hook["command"] and hook != local_hook
        ]
        assert len(progress) == 1
        assert progress[0]["command"] == _DISTRIBUTED_PROGRESS_HOOK_COMMAND
        assert progress[0]["timeout"] == 37
    pre_hooks = [hook for group in merged["hooks"]["PreToolUse"] for hook in group["hooks"]]
    assert local_hook in pre_hooks
    assert expected_guard in pre_hooks
    assert not any(hook["command"] == legacy_guard for hook in pre_hooks)
    assert merged["hooks"]["SessionStart"][0]["hooks"][0]["timeout"] == 83
    after = target.read_bytes()
    assert _run(REPO_ROOT, target, monkeypatch, "--accept-hooks") == 0
    assert target.read_bytes() == after


def test_missing_hooks_preserves_local_options_when_template_matcher_changes() -> None:
    # template 側が matcher を変更したリリースでも、旧 hook の timeout 等が黙って失われないこと。
    legacy_command = _LEGACY_HOOK_COMMANDS[_DISTRIBUTED_PROGRESS_HOOK_COMMAND]
    legacy_hook = {"type": "command", "command": legacy_command, "timeout": 41}
    new_hook = {"type": "command", "command": _DISTRIBUTED_PROGRESS_HOOK_COMMAND}
    target = {"hooks": {"PreToolUse": [{"matcher": "Bash|Task", "hooks": [legacy_hook]}]}}
    template = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [new_hook]}]}}

    assert _settings.missing_hooks(target, template) == [
        ("PreToolUse", {"matcher": "Bash", "hooks": [{**new_hook, "timeout": 41}]}),
    ]
