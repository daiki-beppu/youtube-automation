"""Git control-plane state synchronization boundary.

ADR-0024 の single-writer 前提を保ったまま、state を読む前の fast-forward
pull と、更新後の commit + push を一呼び出しに閉じ込める。分散ロックや競合の
自動解消は行わない。
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

from youtube_automation.core.errors import StateSyncError
from youtube_automation.infrastructure.vcs.state_git import StateGitContext, build_context

T = TypeVar("T")


class StateSyncEventKind(StrEnum):
    """呼び出し側の通知adapterへ渡す同期イベント種別。"""

    NON_FAST_FORWARD = "non_fast_forward"


@dataclass(frozen=True, slots=True)
class StateSyncEvent:
    """secretやremote URLを含まない通知用event。"""

    kind: StateSyncEventKind
    repository: Path
    message: str


EventSink = Callable[[StateSyncEvent], None]
ChangeValidator = Callable[[Path, set[str]], None]


def _run_git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )


def _require_clean(repository: Path) -> None:
    status = _run_git(repository, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        raise StateSyncError("Git worktreeの状態を確認できません")
    if status.stdout:
        raise StateSyncError("state同期の開始前にGit worktreeをcleanにしてください")


def _pull_fast_forward(repository: Path) -> None:
    pulled = _run_git(repository, "pull", "--ff-only")
    if pulled.returncode != 0:
        raise StateSyncError("stateを読む前のgit pull --ff-onlyに失敗しました")


def _paths(repository: Path, *args: str) -> set[str]:
    result = _run_git(repository, *args)
    if result.returncode != 0:
        raise StateSyncError("Gitの変更pathを確認できません")
    return set(result.stdout.splitlines())


def _changed_paths(repository: Path) -> set[str]:
    return (
        _paths(repository, "diff", "--name-only", "--")
        | _paths(repository, "diff", "--cached", "--name-only", "--")
        | _paths(repository, "ls-files", "--others", "--exclude-standard")
    )


def _relative_control_paths(*contexts: StateGitContext) -> set[str]:
    repository = contexts[0].repository
    return {path.relative_to(repository).as_posix() for context in contexts for path in context.control_files}


def _is_non_fast_forward(push: subprocess.CompletedProcess[str]) -> bool:
    output = f"{push.stdout}\n{push.stderr}".lower()
    return "non-fast-forward" in output or "(fetch first)" in output


def pull_then_read(context: StateGitContext, reader: Callable[[], T]) -> T:
    """cleanなrepositoryをfast-forward pullしてからstateを読む。"""

    _require_clean(context.repository)
    _pull_fast_forward(context.repository)
    return reader()


def pull_update_commit_push(
    context: StateGitContext,
    writer: Callable[[], T],
    *,
    commit_message: str,
    on_event: EventSink | None = None,
    change_validator: ChangeValidator | None = None,
) -> T:
    """pull → state更新 → commit → pushをfail-closedで実行する。

    既定ではwriterが変更できるのは ``StateGitContext`` が所有する既知の制御面JSONだけ。
    明示validatorを渡したcallerは同じcommit境界の追加成果物を検証する。push競合は
    自動merge/rebaseせず、通知eventを発火して停止する。
    """

    if not commit_message.strip() or "\n" in commit_message:
        raise StateSyncError("state同期のcommit messageは空でない1行を指定してください")
    _require_clean(context.repository)
    _pull_fast_forward(context.repository)
    before = build_context(context.channel_dir)
    result = writer()
    after = build_context(context.channel_dir)
    changed = _changed_paths(context.repository)
    if change_validator is None:
        allowed = _relative_control_paths(before, after)
        unexpected = changed - allowed
        if unexpected:
            raise StateSyncError("writerがGit制御面state以外を変更したため停止しました")
    else:
        change_validator(context.repository, changed)
    if not changed:
        return result

    paths = sorted(changed)
    added = _run_git(context.repository, "add", "--", *paths)
    if added.returncode != 0:
        raise StateSyncError("Git制御面stateをstageできません")
    committed = _run_git(context.repository, "commit", "-m", commit_message, "--", *paths)
    if committed.returncode != 0:
        raise StateSyncError("Git制御面stateをcommitできません")
    pushed = _run_git(context.repository, "push", "--porcelain")
    if pushed.returncode == 0:
        return result
    if _is_non_fast_forward(pushed):
        event = StateSyncEvent(
            kind=StateSyncEventKind.NON_FAST_FORWARD,
            repository=context.repository,
            message="state pushがnon-fast-forwardで拒否されました。自動merge/rebaseは行いません。",
        )
        if on_event is not None:
            on_event(event)
        raise StateSyncError("state pushがnon-fast-forwardで拒否されました")
    raise StateSyncError("Git制御面stateをpushできません")
