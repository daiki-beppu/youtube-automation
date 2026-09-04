from __future__ import annotations

import fcntl
import subprocess
from pathlib import Path

import pytest

from youtube_automation.commands.system import session_start


def _repo(tmp_path: Path, pin: str) -> Path:
    repo = tmp_path / "channel"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname="channel"\ndependencies=["youtube-channels-automation"]\n'
        "[tool.uv.sources]\nyoutube-channels-automation="
        f'{{git="https://github.com/daiki-beppu/youtube-automation", {pin}}}\n',
        encoding="utf-8",
    )
    return repo


def _environment(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    for name in ("CI", "GITHUB_ACTIONS", "YOUTUBE_AUTOMATION_DISABLE_SESSION_UPDATE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))


@pytest.mark.parametrize("name", ["YOUTUBE_AUTOMATION_DISABLE_SESSION_UPDATE", "CI", "GITHUB_ACTIONS"])
def test_immediate_environment_gates_are_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, name: str
) -> None:
    repo = _repo(tmp_path, 'branch="main"')
    _environment(monkeypatch, repo)
    monkeypatch.setenv(name, "1")
    monkeypatch.setattr(session_start, "_command", lambda *args, **kwargs: pytest.fail("command must not run"))
    assert session_start.main([]) == 0
    assert capsys.readouterr().out == ""


def test_main_diff_applies_commit_and_reports_followups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _repo(tmp_path, 'branch="main"')
    _environment(monkeypatch, repo)
    monkeypatch.setattr(session_start, "_gate_reason", lambda root: None)
    commands: list[list[str]] = []

    def fake_command(command, root, *, timeout=None):
        commands.append(command)
        if command[-1] == "check":
            return subprocess.CompletedProcess(command, 1, "", "")
        if "migrate-config" in command:
            return subprocess.CompletedProcess(command, 0, "dry-run 完了: 1 ファイル（変更なし）", "")
        if "yt-document-render" in command:
            return subprocess.CompletedProcess(command, 1, "", "")
        return subprocess.CompletedProcess(command, 0, "Claude Code を再起動してください", "")

    monkeypatch.setattr(session_start, "_command", fake_command)
    assert session_start.main([]) == 0
    assert ["uv", "run", "yt-automation-update", "apply", "--commit", "--accept-hooks"] in commands
    assert not any("--force-sync" in command for command in commands)
    output = capsys.readouterr().out
    assert "要 migrate, 要 render, Claude Code を再起動してください" in output
    assert len(output.splitlines()) <= 3


def test_synced_main_and_sha_are_quiet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    main_repo = _repo(tmp_path, 'branch="main"')
    _environment(monkeypatch, main_repo)
    monkeypatch.setattr(session_start, "_command", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, "", ""))
    assert session_start.main([]) == 0
    assert capsys.readouterr().out == ""

    sha_repo = tmp_path / "sha"
    sha_repo.mkdir()
    (sha_repo / "pyproject.toml").write_text(
        '[project]\nname="channel"\ndependencies=["youtube-channels-automation"]\n'
        '[tool.uv.sources]\nyoutube-channels-automation={git="https://github.com/daiki-beppu/youtube-automation", rev="'
        + "a" * 40
        + '"}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(sha_repo))
    assert session_start.main([]) == 0
    assert capsys.readouterr().out == ""


def test_tag_diff_only_notifies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    repo = _repo(tmp_path, 'tag="v5.7.1"')
    _environment(monkeypatch, repo)
    commands: list[list[str]] = []

    def fake_command(command, root, *, timeout=None):
        commands.append(command)
        return subprocess.CompletedProcess(command, 1, "", "")

    monkeypatch.setattr(session_start, "_command", fake_command)
    assert session_start.main([]) == 0
    assert len(commands) == 1
    assert "新しい release" in capsys.readouterr().out


def test_failed_apply_reports_local_fix_and_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    repo = _repo(tmp_path, 'branch="main"')
    _environment(monkeypatch, repo)
    monkeypatch.setattr(session_start, "_gate_reason", lambda root: None)

    def fake_command(command, root, *, timeout=None):
        code = 1
        error = "local fix 差分" if "apply" in command else ""
        return subprocess.CompletedProcess(command, code, "", error)

    monkeypatch.setattr(session_start, "_command", fake_command)
    assert session_start.main([]) == 0
    output = capsys.readouterr().out
    assert "apply --force-sync --commit" in output
    assert "uv run yt-automation-update apply --commit" in output
    assert len(output.splitlines()) == 2


def test_lock_contention_prints_one_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    repo = _repo(tmp_path, 'branch="main"')
    _environment(monkeypatch, repo)
    lock_path = repo / ".automation-run" / "session-update.lock"
    lock_path.parent.mkdir()
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert session_start.main([]) == 0
    assert capsys.readouterr().out.splitlines() == ["[yt-session-start] 別 session が追従中です"]


@pytest.mark.parametrize(
    "reason",
    [
        "linked worktree のため自動追従しません",
        "デフォルトブランチ以外のため自動追従しません",
        "追跡 upstream branch がないため自動追従しません",
        "追跡ファイルに未コミット変更があるため自動追従しません",
    ],
)
def test_missing_safety_condition_only_notifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, reason: str
) -> None:
    repo = _repo(tmp_path, 'branch="main"')
    _environment(monkeypatch, repo)
    monkeypatch.setattr(session_start, "_gate_reason", lambda root: reason)
    calls = 0

    def fake_command(command, root, *, timeout=None):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 1, "", "")

    monkeypatch.setattr(session_start, "_command", fake_command)
    assert session_start.main([]) == 0
    assert calls == 1
    assert reason in capsys.readouterr().out


def test_check_timeout_is_quiet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    repo = _repo(tmp_path, 'branch="main"')
    _environment(monkeypatch, repo)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("check", 3)

    monkeypatch.setattr(session_start, "_command", timeout)
    assert session_start.main([]) == 0
    assert capsys.readouterr().out == ""


def test_four_condition_gate_uses_tracking_branch_and_ignores_untracked(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path("/channel")
    outputs = {
        ("rev-parse", "--path-format=absolute", "--git-dir"): "/channel/.git",
        ("rev-parse", "--path-format=absolute", "--git-common-dir"): "/channel/.git",
        ("branch", "--show-current"): "main",
        ("symbolic-ref", "--short", "refs/remotes/origin/HEAD"): "origin/main",
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"): "origin/main",
        ("status", "--porcelain", "--untracked-files=no"): "",
    }
    monkeypatch.setattr(session_start, "_git_output", lambda root, *args: outputs.get(args))
    assert session_start._gate_reason(root) is None
