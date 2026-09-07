"""Truth Eye の封印成果物だけを Git commit する adapter。"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from youtube_automation.infrastructure.vcs._git import parse_status_paths, run_git


@dataclass(frozen=True, slots=True)
class TrainingCommitResult:
    committed: bool
    commit: str | None = None
    reason: str | None = None
    changed_files: tuple[str, ...] = ()


def commit_training_files(repository: Path, paths: tuple[Path, Path], message: str) -> TrainingCommitResult:
    """作業ツリーが clean な場合だけ、指定された 2 path を commit する。"""
    try:
        root_result = run_git(repository, "rev-parse", "--show-toplevel")
        if root_result.returncode != 0:
            return TrainingCommitResult(False, reason="Git リポジトリではないため自動 commit を見送りました")
        root = Path(root_result.stdout.strip()).resolve()
        relative_paths = tuple(path.resolve().relative_to(root).as_posix() for path in paths)

        dirty = _tracked_changes(root)
        if dirty:
            return TrainingCommitResult(
                False,
                reason="対象外の tracked ファイルに未コミット変更があるため自動 commit を見送りました",
                changed_files=dirty,
            )

        if _identity_missing(root):
            return TrainingCommitResult(False, reason="Git identity が未設定のため自動 commit を見送りました")

        added = run_git(root, "add", "--", *relative_paths)
        if added.returncode != 0:
            return TrainingCommitResult(False, reason=f"git add に失敗しました: {_git_error(added)}")
        committed = run_git(root, "commit", "-m", message, "--", *relative_paths)
        if committed.returncode != 0:
            run_git(root, "reset", "--quiet", "--", *relative_paths)
            return TrainingCommitResult(False, reason=f"git commit に失敗しました: {_git_error(committed)}")
        revision = run_git(root, "rev-parse", "--short", "HEAD")
        return TrainingCommitResult(True, commit=revision.stdout.strip())
    except OSError as error:
        return TrainingCommitResult(False, reason=f"Git の実行に失敗したため自動 commit を見送りました: {error}")
    except ValueError:
        return TrainingCommitResult(False, reason="生成ファイルが Git リポジトリ外のため自動 commit を見送りました")


def _tracked_changes(repository: Path) -> tuple[str, ...]:
    status = run_git(repository, "status", "--porcelain=v1", "-z", "--untracked-files=no")
    return parse_status_paths(status.stdout)


def _identity_missing(repository: Path) -> bool:
    """`user.name` / `user.email` を 1 回の `git config` で確認する。"""
    result = run_git(repository, "config", "--get-regexp", r"^user\.(name|email)$")
    if result.returncode != 0:
        return True
    # system → global → local の順に出力されるため、後勝ちで実効値を決める。
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition(" ")
        values[key] = value.strip()
    return not all(values.get(key) for key in ("user.name", "user.email"))


def _git_error(result: subprocess.CompletedProcess[str]) -> str:
    return result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
