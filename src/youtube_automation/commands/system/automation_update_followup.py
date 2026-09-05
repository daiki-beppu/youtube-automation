"""`yt-automation-update apply` 後の要対応判定を追従系 CLI 間で共有する。"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

CommandRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]

_MIGRATE_PENDING_MARKER = "dry-run 完了:"


def migrate_action(path: Path, run: CommandRunner) -> str | None:
    """未移行の skill-config があれば要対応を返す。起動できなければ検査失敗を返す。"""
    command = ["uv", "run", "yt-skills", "migrate-config", "--channel-dir", str(path), "--dry-run"]
    try:
        completed = run(command, path)
    except OSError:
        return "migrate 検査に失敗"
    return "要 migrate" if _MIGRATE_PENDING_MARKER in completed.stdout else None


def render_action(path: Path, run: CommandRunner) -> str | None:
    """再生成が要る document pair があれば要対応を返す。起動できなければ検査失敗を返す。"""
    try:
        completed = run(["uv", "run", "yt-document-render", "--check", "--all"], path)
    except OSError:
        return "render 検査に失敗"
    return "要 render" if completed.returncode != 0 else None
