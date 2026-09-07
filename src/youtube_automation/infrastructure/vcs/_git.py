"""`infrastructure/vcs/` 内の adapter が共有する git subprocess 実行 helper。"""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """`repository` を cwd として git を実行し、例外を投げず結果をそのまま返す。"""
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )


__all__ = ["run_git"]
