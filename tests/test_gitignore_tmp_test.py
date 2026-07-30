"""Git が pytest 一時生成物を実際に ignore する契約。"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_git_ignores_pytest_temporary_artifacts() -> None:
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "--no-index",
            "--quiet",
            ".tmp_test/pytest-of-mba/uv-08f4a866285ed88b.lock",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
