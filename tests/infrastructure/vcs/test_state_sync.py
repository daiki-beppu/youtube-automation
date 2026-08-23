from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from youtube_automation.core.errors import StateSyncError
from youtube_automation.domains.notifications import NotificationEvent, NotificationEventKind
from youtube_automation.infrastructure.vcs.state_git import build_context
from youtube_automation.infrastructure.vcs.state_sync import (
    pull_then_read,
    pull_update_commit_push,
)


_NOTIFICATION_CHANNEL = "ambient-lab"
_NOTIFICATION_COLLECTION = "sample"


def _git(directory: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write_state(repository: Path, phase: str) -> Path:
    state = repository / "collections" / "planning" / "sample" / "workflow-state.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"phase": phase}) + "\n", encoding="utf-8")
    return state


def _clone(remote: Path, destination: Path) -> Path:
    subprocess.run(
        ["git", "clone", str(remote), str(destination)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(destination, "config", "user.email", "test@example.com")
    _git(destination, "config", "user.name", "Test User")
    return destination


@pytest.fixture
def repositories(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "--initial-branch=main")
    _git(seed, "config", "user.email", "test@example.com")
    _git(seed, "config", "user.name", "Test User")
    (seed / ".gitignore").write_text("\n", encoding="utf-8")
    _write_state(seed, "planned")
    _git(seed, "add", ".gitignore", "collections")
    _git(seed, "commit", "-m", "initial")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    return remote, _clone(remote, tmp_path / "local-a"), _clone(remote, tmp_path / "local-b")


def test_pull_then_read_observes_remote_state(repositories: tuple[Path, Path, Path]) -> None:
    _, local_a, local_b = repositories
    _write_state(local_b, "generated")
    _git(local_b, "add", "collections")
    _git(local_b, "commit", "-m", "remote update")
    _git(local_b, "push")

    value = pull_then_read(
        build_context(local_a),
        lambda: json.loads(_write_target(local_a).read_text(encoding="utf-8")),
    )

    assert value["phase"] == "generated"


def test_update_commits_and_pushes_control_state(repositories: tuple[Path, Path, Path]) -> None:
    remote, local_a, _ = repositories
    state = _write_target(local_a)

    result = pull_update_commit_push(
        build_context(local_a),
        lambda: (_write_state(local_a, "mastered"), "updated")[1],
        commit_message="chore: stateを更新する",
        notification_channel=_NOTIFICATION_CHANNEL,
        notification_collection=_NOTIFICATION_COLLECTION,
    )

    verifier = _clone(remote, local_a.parent / "verifier")
    assert result == "updated"
    assert json.loads(_write_target(verifier).read_text(encoding="utf-8"))["phase"] == "mastered"
    assert _git(local_a, "status", "--porcelain") == ""
    assert state.is_file()


def test_concurrent_push_rejection_stops_and_emits_event(
    repositories: tuple[Path, Path, Path],
) -> None:
    remote, local_a, local_b = repositories
    events: list[NotificationEvent] = []

    def racing_update() -> None:
        _write_state(local_a, "local-a")
        pull_update_commit_push(
            build_context(local_b),
            lambda: _write_state(local_b, "local-b"),
            commit_message="chore: competing state",
            notification_channel=_NOTIFICATION_CHANNEL,
            notification_collection=_NOTIFICATION_COLLECTION,
        )

    with pytest.raises(StateSyncError, match="non-fast-forward"):
        pull_update_commit_push(
            build_context(local_a),
            racing_update,
            commit_message="chore: losing state",
            notification_channel=_NOTIFICATION_CHANNEL,
            notification_collection=_NOTIFICATION_COLLECTION,
            on_event=events.append,
        )

    verifier = _clone(remote, local_a.parent / "race-verifier")
    assert json.loads(_write_target(verifier).read_text(encoding="utf-8"))["phase"] == "local-b"
    assert [event.kind for event in events] == [NotificationEventKind.NON_FAST_FORWARD_STOPPED]
    assert events[0].stage == "state-sync"
    assert (events[0].channel, events[0].collection) == (_NOTIFICATION_CHANNEL, _NOTIFICATION_COLLECTION)
    assert len(_git(local_a, "rev-list", "--parents", "-n", "1", "HEAD").split()) == 2
    assert _git(local_a, "status", "--porcelain") == ""


def test_update_rejects_unrelated_dirty_file_before_writer(
    repositories: tuple[Path, Path, Path],
) -> None:
    _, local_a, _ = repositories
    unrelated = local_a / "notes.txt"
    unrelated.write_text("dirty\n", encoding="utf-8")
    called = False

    def writer() -> None:
        nonlocal called
        called = True

    with pytest.raises(StateSyncError, match="clean"):
        pull_update_commit_push(
            build_context(local_a),
            writer,
            commit_message="chore: stateを更新する",
            notification_channel=_NOTIFICATION_CHANNEL,
            notification_collection=_NOTIFICATION_COLLECTION,
        )

    assert called is False


def test_update_rejects_changes_outside_control_files(
    repositories: tuple[Path, Path, Path],
) -> None:
    _, local_a, _ = repositories
    readme = local_a / "README.md"

    with pytest.raises(StateSyncError, match="制御面"):
        pull_update_commit_push(
            build_context(local_a),
            lambda: readme.write_text("unexpected\n", encoding="utf-8"),
            commit_message="chore: stateを更新する",
            notification_channel=_NOTIFICATION_CHANNEL,
            notification_collection=_NOTIFICATION_COLLECTION,
        )

    assert not readme.is_file() or _git(local_a, "status", "--porcelain") == "?? README.md"


def test_update_without_changes_does_not_create_commit(repositories: tuple[Path, Path, Path]) -> None:
    _, local_a, _ = repositories
    before = _git(local_a, "rev-parse", "HEAD")

    result = pull_update_commit_push(
        build_context(local_a),
        lambda: "unchanged",
        commit_message="chore: stateを更新する",
        notification_channel=_NOTIFICATION_CHANNEL,
        notification_collection=_NOTIFICATION_COLLECTION,
    )

    assert result == "unchanged"
    assert _git(local_a, "rev-parse", "HEAD") == before


def _write_target(repository: Path) -> Path:
    return repository / "collections" / "planning" / "sample" / "workflow-state.json"
