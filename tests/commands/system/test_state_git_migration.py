from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from youtube_automation.commands.system.skills_sync import main
from youtube_automation.commands.system.skills_sync._state_git import STATE_GITIGNORE_MARKER


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _init_repo(path: Path, *, gitignore: str = "collections/**\n*.json\n") -> Path:
    path.mkdir()
    assert _git(path, "init", "-q").returncode == 0
    assert _git(path, "config", "user.email", "test@example.com").returncode == 0
    assert _git(path, "config", "user.name", "Test").returncode == 0
    (path / ".gitignore").write_text(gitignore, encoding="utf-8")
    (path / "config" / "channel").mkdir(parents=True)
    (path / "config" / "channel" / "meta.json").write_text('{"channel": {"name": "test"}}\n', encoding="utf-8")
    assert _git(path, "add", ".gitignore").returncode == 0
    assert _git(path, "add", "-f", "config/channel/meta.json").returncode == 0
    assert _git(path, "commit", "-qm", "initial").returncode == 0
    return path


def _write_control_files(channel: Path) -> tuple[Path, ...]:
    collection = channel / "collections" / "planning" / "demo"
    docs = collection / "20-documentation"
    docs.mkdir(parents=True)
    state = collection / "workflow-state.json"
    tracking = docs / "upload_tracking.json"
    post_publish = channel / "post_publish_history.json"
    pinned = channel / "pinned_comment_history.json"
    state.write_text('{"phase": "planning"}\n', encoding="utf-8")
    tracking.write_text('{"schema_version": 3}\n', encoding="utf-8")
    post_publish.write_text("[]\n", encoding="utf-8")
    pinned.write_text("[]\n", encoding="utf-8")
    return state, tracking, post_publish, pinned


def test_dry_run_lists_only_channel_control_files_without_mutation(tmp_path: Path, capsys) -> None:
    channel = _init_repo(tmp_path / "channel")
    files = _write_control_files(channel)
    nested = channel / ".claude" / "worktrees" / "other" / "collections" / "live" / "wrong"
    nested.mkdir(parents=True)
    (nested / "workflow-state.json").write_text('{"secret": "do-not-read"}\n', encoding="utf-8")
    before_ignore = (channel / ".gitignore").read_bytes()
    before_status = _git(channel, "status", "--porcelain=v1", "--ignored").stdout

    assert main(["migrate-state-git", "--channel-dir", str(channel), "--dry-run"]) == 0

    output = capsys.readouterr().out
    assert all(path.relative_to(channel).as_posix() in output for path in files)
    assert ".claude/worktrees" not in output
    assert (channel / ".gitignore").read_bytes() == before_ignore
    assert _git(channel, "status", "--porcelain=v1", "--ignored").stdout == before_status


def test_apply_stages_policy_and_control_files_then_check_passes_after_commit(tmp_path: Path, capsys) -> None:
    channel = _init_repo(tmp_path / "channel")
    files = _write_control_files(channel)

    assert main(["migrate-state-git", "--channel-dir", str(channel)]) == 0

    ignore = (channel / ".gitignore").read_text(encoding="utf-8")
    assert STATE_GITIGNORE_MARKER in ignore
    staged = set(_git(channel, "diff", "--cached", "--name-only").stdout.splitlines())
    assert staged == {".gitignore", *(path.relative_to(channel).as_posix() for path in files)}
    assert main(["migrate-state-git", "--channel-dir", str(channel), "--check"]) == 1
    assert "commit" in capsys.readouterr().err

    assert _git(channel, "commit", "-qm", "manage state").returncode == 0
    assert main(["migrate-state-git", "--channel-dir", str(channel), "--check"]) == 0


def test_apply_is_idempotent_while_generated_changes_are_staged(tmp_path: Path) -> None:
    channel = _init_repo(tmp_path / "channel")
    _write_control_files(channel)
    assert main(["migrate-state-git", "--channel-dir", str(channel)]) == 0
    before_ignore = (channel / ".gitignore").read_bytes()
    before_index = _git(channel, "diff", "--cached", "--binary").stdout

    assert main(["migrate-state-git", "--channel-dir", str(channel)]) == 0

    assert (channel / ".gitignore").read_bytes() == before_ignore
    assert _git(channel, "diff", "--cached", "--binary").stdout == before_index


@pytest.mark.parametrize("kind", ["staged", "dirty"])
def test_apply_refuses_unrelated_repository_changes(tmp_path: Path, capsys, kind: str) -> None:
    channel = _init_repo(tmp_path / "channel")
    _write_control_files(channel)
    unrelated = channel / "notes.md"
    unrelated.write_text("before\n", encoding="utf-8")
    assert _git(channel, "add", "notes.md").returncode == 0
    assert _git(channel, "commit", "-qm", "notes").returncode == 0
    unrelated.write_text("after\n", encoding="utf-8")
    if kind == "staged":
        assert _git(channel, "add", "notes.md").returncode == 0

    assert main(["migrate-state-git", "--channel-dir", str(channel)]) == 1

    assert "作業ツリー" in capsys.readouterr().err
    assert STATE_GITIGNORE_MARKER not in (channel / ".gitignore").read_text(encoding="utf-8")


def test_secret_bearing_tracking_fails_closed_without_leaking_value(tmp_path: Path, capsys) -> None:
    channel = _init_repo(tmp_path / "channel")
    _, tracking, *_ = _write_control_files(channel)
    secret = "ya29.secret-value"
    tracking.write_text(json.dumps({"resume_session_uri": secret}), encoding="utf-8")

    assert main(["migrate-state-git", "--channel-dir", str(channel), "--dry-run"]) == 1

    captured = capsys.readouterr()
    assert "secret" in captured.err.lower()
    assert secret not in captured.out + captured.err
    assert STATE_GITIGNORE_MARKER not in (channel / ".gitignore").read_text(encoding="utf-8")


def test_missing_gitignore_and_non_repository_fail_closed(tmp_path: Path, capsys) -> None:
    not_repo = tmp_path / "not-repo"
    not_repo.mkdir()
    assert main(["migrate-state-git", "--channel-dir", str(not_repo), "--check"]) == 1
    assert "Git repository" in capsys.readouterr().err

    channel = _init_repo(tmp_path / "channel")
    (channel / ".gitignore").unlink()
    assert main(["migrate-state-git", "--channel-dir", str(channel), "--dry-run"]) == 1
    assert ".gitignore" in capsys.readouterr().err


def test_symlinked_collection_is_rejected_without_reading_external_data(tmp_path: Path, capsys) -> None:
    channel = _init_repo(tmp_path / "channel")
    outside = tmp_path / "real-data"
    outside.mkdir()
    (outside / "workflow-state.json").write_text('{"phase": "secret outside data"}\n', encoding="utf-8")
    live = channel / "collections" / "live"
    live.mkdir(parents=True)
    (live / "linked").symlink_to(outside, target_is_directory=True)

    assert main(["migrate-state-git", "--channel-dir", str(channel), "--dry-run"]) == 1

    captured = capsys.readouterr()
    assert "symlink" in captured.err
    assert "secret outside data" not in captured.out + captured.err


def test_check_rejects_untracked_control_file_even_when_policy_exists(tmp_path: Path, capsys) -> None:
    channel = _init_repo(tmp_path / "channel", gitignore="")
    state, *_ = _write_control_files(channel)
    with (channel / ".gitignore").open("a", encoding="utf-8") as stream:
        stream.write("\n" + STATE_GITIGNORE_MARKER + "\n")
    assert _git(channel, "add", ".gitignore").returncode == 0
    assert _git(channel, "commit", "-qm", "policy").returncode == 0

    assert main(["migrate-state-git", "--channel-dir", str(channel), "--check"]) == 1

    assert state.relative_to(channel).as_posix() in capsys.readouterr().err


def test_apply_moves_existing_policy_to_end_when_later_rule_reignores_state(tmp_path: Path) -> None:
    channel = _init_repo(tmp_path / "channel", gitignore="")
    template = (
        "# yt-state-git control plane (ADR-0024)\n"
        "!collections/\n"
        "!collections/**/\n"
        "!collections/**/workflow-state.json\n"
        "!collections/**/20-documentation/upload_tracking.json\n"
        "!post_publish_history.json\n"
        "!pinned_comment_history.json\n"
    )
    (channel / ".gitignore").write_text(template + "collections/**\n", encoding="utf-8")
    assert _git(channel, "add", ".gitignore").returncode == 0
    assert _git(channel, "commit", "-qm", "stale policy").returncode == 0
    state, *_ = _write_control_files(channel)

    assert main(["migrate-state-git", "--channel-dir", str(channel), "--check"]) == 1
    assert main(["migrate-state-git", "--channel-dir", str(channel)]) == 0

    assert (channel / ".gitignore").read_text(encoding="utf-8").endswith(template)
    assert state.relative_to(channel).as_posix() in _git(channel, "diff", "--cached", "--name-only").stdout
