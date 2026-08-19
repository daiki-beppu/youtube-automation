"""Explicit migration of downstream workflow control-plane JSON into Git."""

from __future__ import annotations

import argparse
import difflib
import sys

from youtube_automation.core.errors import ConfigError
from youtube_automation.infrastructure.vcs.state_git import (
    STATE_GITIGNORE_MARKER,
    StateGitContext,
    apply_state_git,
    build_context,
    check_state_git,
    planned_gitignore,
)


def _print_plan(context: StateGitContext) -> None:
    before = context.gitignore.read_text(encoding="utf-8").splitlines(keepends=True)
    after = planned_gitignore(context).splitlines(keepends=True)
    print(
        "".join(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"{context.gitignore.relative_to(context.repository)} (before)",
                tofile=f"{context.gitignore.relative_to(context.repository)} (after)",
            )
        ),
        end="",
    )
    for path in context.control_files:
        print(f"Git管理へ追加: {path.relative_to(context.channel_dir).as_posix()}")


def cmd_migrate_state_git(args: argparse.Namespace) -> int:
    try:
        context = build_context(args.channel_dir)
        if args.check:
            diagnostics = check_state_git(context)
            if diagnostics:
                for diagnostic in diagnostics:
                    print(f"error: {diagnostic}", file=sys.stderr)
                return 1
            print("state Git管理チェック合格")
            return 0
        from youtube_automation.infrastructure.vcs.state_git import validate_migration_worktree

        validate_migration_worktree(context)
        _print_plan(context)
        if args.dry_run:
            print("dry-run 完了（変更なし）")
            return 0
        apply_state_git(context)
    except (ConfigError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("移行準備完了: 差分を確認してcommitしてください")
    return 0


__all__ = ["STATE_GITIGNORE_MARKER", "cmd_migrate_state_git"]
