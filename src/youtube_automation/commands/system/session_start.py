"""SessionStart で安全な場合だけ upstream 追従を遅延実行する CLI。"""

from __future__ import annotations

import argparse
import fcntl
import os
import subprocess
from pathlib import Path

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.commands.system.automation_update import _load_pyproject, _resolve_repo_root
from youtube_automation.commands.system.automation_update_refs import _detect_pin
from youtube_automation.core.errors import ConfigError

_PREFIX = "[yt-session-start]"
_CHECK_TIMEOUT_SECONDS = 3


def _command(command: list[str], root: Path, *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=root, capture_output=True, text=True, check=False, timeout=timeout)


def _git_output(root: Path, *arguments: str) -> str | None:
    completed = _command(["git", *arguments], root)
    return completed.stdout.strip() if completed.returncode == 0 else None


def _gate_reason(root: Path) -> str | None:
    git_dir = _git_output(root, "rev-parse", "--path-format=absolute", "--git-dir")
    common_dir = _git_output(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if git_dir is None or common_dir is None or Path(git_dir) != Path(common_dir):
        return "linked worktree のため自動追従しません"
    branch = _git_output(root, "branch", "--show-current")
    default_ref = _git_output(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    default_branch = default_ref.rsplit("/", 1)[-1] if default_ref else "main"
    if branch != default_branch:
        return f"デフォルトブランチ以外（{branch or 'detached'}）のため自動追従しません"
    if _git_output(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}") is None:
        return "追跡 upstream branch がないため自動追従しません"
    status = _git_output(root, "status", "--porcelain", "--untracked-files=no")
    if status is None:
        return "作業ツリーを確認できないため自動追従しません"
    if status:
        return "追跡ファイルに未コミット変更があるため自動追従しません"
    return None


def _followup_actions(root: Path, apply_output: str) -> list[str]:
    actions: list[str] = []
    migrate = _command(["uv", "run", "yt-skills", "migrate-config", "--channel-dir", str(root), "--dry-run"], root)
    if "dry-run 完了:" in migrate.stdout:
        actions.append("要 migrate")
    render = _command(["uv", "run", "yt-document-render", "--check", "--all"], root)
    if render.returncode != 0:
        actions.append("要 render")
    if "Claude Code を再起動" in apply_output:
        actions.append("Claude Code を再起動してください")
    return actions


def _run(_: argparse.Namespace) -> int:
    if (
        os.environ.get("YOUTUBE_AUTOMATION_DISABLE_SESSION_UPDATE") == "1"
        or os.environ.get("CI")
        or os.environ.get("GITHUB_ACTIONS")
    ):
        return 0
    try:
        root = _resolve_repo_root(os.environ.get("CLAUDE_PROJECT_DIR"))
        pin = _detect_pin(_load_pyproject(root / "pyproject.toml"))
        if pin.kind == "sha":
            return 0
        lock_path = root / ".automation-run" / "session-update.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("w", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(f"{_PREFIX} 別 session が追従中です")
                return 0
            check = _command(["uv", "run", "yt-automation-update", "check"], root, timeout=_CHECK_TIMEOUT_SECONDS)
            if check.returncode != 1:
                return 0
            if pin.kind == "tag":
                print(f"{_PREFIX} 新しい release があります。yt-channels update --tag <tag> で追従してください")
                return 0
            reason = _gate_reason(root)
            if reason:
                print(f"{_PREFIX} {reason}")
                print(f"{_PREFIX} 上流に更新があります。yt-channels update で追従してください")
                return 0
            apply = _command(["uv", "run", "yt-automation-update", "apply", "--commit", "--accept-hooks"], root)
            output = "\n".join((apply.stdout, apply.stderr))
            if apply.returncode != 0:
                if "local fix" in output:
                    print(
                        f"{_PREFIX} local fix あり。上書きするなら apply --force-sync --commit、"
                        "共有するなら /skill-feedback"
                    )
                else:
                    print(f"{_PREFIX} 追従に失敗しました")
                print(f"{_PREFIX} 復旧: uv run yt-automation-update apply --commit")
                return 0
            print(f"{_PREFIX} upstream への追従と commit が完了しました")
            try:
                actions = _followup_actions(root, output)
            except (OSError, subprocess.TimeoutExpired):
                actions = ["更新後の migrate / render 検査に失敗しました。手動で確認してください"]
            if actions:
                print(f"{_PREFIX} 要対応: {', '.join(actions)}")
    except (ConfigError, OSError, subprocess.TimeoutExpired):
        return 0
    return 0


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="yt-session-start", description="安全な SessionStart で upstream へ遅延追従する"
    )


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, _run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
