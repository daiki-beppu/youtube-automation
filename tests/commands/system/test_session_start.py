from __future__ import annotations

import fcntl
import os
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


def test_tag_diff_names_the_release_from_check_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _repo(tmp_path, 'tag="v5.7.1"')
    _environment(monkeypatch, repo)
    stdout = "pin 形式: tag pin (v5.7.1)\nupstream 最新リリース: v5.7.2\n→ 差分あり: v5.7.1 → v5.7.2\n"
    monkeypatch.setattr(
        session_start, "_command", lambda command, root, **kwargs: subprocess.CompletedProcess(command, 1, stdout, "")
    )
    assert session_start.main([]) == 0
    assert "新しい release v5.7.2 があります。yt-channels update --tag v5.7.2 で追従してください" in capsys.readouterr().out


def test_blocked_main_notification_names_the_upstream_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    repo = _repo(tmp_path, 'branch="main"')
    _environment(monkeypatch, repo)
    monkeypatch.setattr(session_start, "_gate_reason", lambda root: "linked worktree のため自動追従しません")
    stdout = f"upstream main HEAD: {'b' * 40}\nuv.lock 解決済み sha: {'a' * 40}\n"
    monkeypatch.setattr(
        session_start, "_command", lambda command, root, **kwargs: subprocess.CompletedProcess(command, 1, stdout, "")
    )
    assert session_start.main([]) == 0
    assert "上流 main の最新は bbbbbbb です。yt-channels update で追従してください" in capsys.readouterr().out


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


@pytest.mark.parametrize(
    ("changed_command", "value", "reason"),
    [
        (None, None, None),
        (("rev-parse", "--path-format=absolute", "--git-dir"), "/main/.git/worktrees/channel", "linked worktree"),
        (("branch", "--show-current"), "feature", "デフォルトブランチ以外"),
        (("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"), None, "追跡 upstream"),
        (("status", "--porcelain", "--untracked-files=no"), " M tracked.txt", "未コミット変更"),
        (("status", "--porcelain", "--untracked-files=no"), None, "確認できない"),
    ],
)
def test_four_condition_gate_uses_tracking_branch_and_ignores_untracked(
    monkeypatch: pytest.MonkeyPatch, changed_command, value, reason
) -> None:
    root = Path("/channel")
    outputs = {
        ("rev-parse", "--path-format=absolute", "--git-dir"): "/channel/.git",
        ("rev-parse", "--path-format=absolute", "--git-common-dir"): "/channel/.git",
        ("branch", "--show-current"): "main",
        ("symbolic-ref", "--short", "refs/remotes/origin/HEAD"): "origin/main",
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"): "origin/main",
        ("status", "--porcelain", "--untracked-files=no"): "",
    }
    if changed_command is not None:
        outputs[changed_command] = value
    monkeypatch.setattr(session_start, "_git_output", lambda root, *args: outputs.get(args))
    actual = session_start._gate_reason(root)
    assert actual is None if reason is None else reason in actual


@pytest.mark.parametrize("failing_command", ["migrate-config", "yt-document-render"])
def test_successful_commit_is_reported_when_followup_cannot_start(
    tmp_path: Path, monkeypatch, capsys, failing_command
) -> None:
    repo = _repo(tmp_path, 'branch="main"')
    _environment(monkeypatch, repo)
    monkeypatch.setattr(session_start, "_gate_reason", lambda root: None)

    def command(args, root, **kwargs):
        if failing_command in args:
            raise OSError("cannot start")
        return subprocess.CompletedProcess(args, 1 if args[-1] == "check" else 0, "", "")

    monkeypatch.setattr(session_start, "_command", command)
    assert session_start.main([]) == 0
    output = capsys.readouterr().out
    assert "追従と commit が完了" in output
    assert "検査に失敗" in output
    assert len(output.splitlines()) <= 3


# 実行環境の git 設定（既定ブランチ名・署名・hooksPath）に結果が左右されないよう遮断する。
_GIT_ENVIRONMENT = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "session-start-test",
    "GIT_AUTHOR_EMAIL": "session-start-test@example.invalid",
    "GIT_COMMITTER_NAME": "session-start-test",
    "GIT_COMMITTER_EMAIL": "session-start-test@example.invalid",
}


def _git(cwd: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        env={**os.environ, **_GIT_ENVIRONMENT},
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """origin/HEAD と upstream を持つ clean な main checkout。"""
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"
    seed.mkdir()
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    _git(seed, "init", "--initial-branch=main")
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "--quiet", "--message", "seed")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "--quiet", "origin", "main")
    _git(tmp_path, "clone", "--quiet", str(remote), str(checkout))
    return checkout


def test_gate_allows_clean_default_branch_with_untracked_files(clone: Path) -> None:
    (clone / "scratch.txt").write_text("untracked\n", encoding="utf-8")
    assert session_start._gate_reason(clone) is None


def test_gate_rejects_tracked_dirty_worktree(clone: Path) -> None:
    (clone / "README.md").write_text("changed\n", encoding="utf-8")
    assert session_start._gate_reason(clone) == "追跡ファイルに未コミット変更があるため自動追従しません"


def test_gate_rejects_non_default_branch(clone: Path) -> None:
    _git(clone, "switch", "--quiet", "--create", "feature")
    assert session_start._gate_reason(clone) == "デフォルトブランチ以外（feature）のため自動追従しません"


def test_gate_rejects_detached_head(clone: Path) -> None:
    _git(clone, "checkout", "--quiet", "--detach", "HEAD")
    assert session_start._gate_reason(clone) == "デフォルトブランチ以外（detached）のため自動追従しません"


def test_gate_rejects_branch_without_upstream(clone: Path) -> None:
    _git(clone, "branch", "--unset-upstream")
    assert session_start._gate_reason(clone) == "追跡 upstream branch がないため自動追従しません"


def test_gate_rejects_linked_worktree(clone: Path, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    _git(clone, "worktree", "add", "--quiet", "-b", "topic", str(linked))
    assert session_start._gate_reason(linked) == "linked worktree のため自動追従しません"
