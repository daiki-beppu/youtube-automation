"""Git が OAuth token files を実際に ignore する契約。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("relative_path", ("auth/token.json", "auth/token_streaming.json"))
def test_git_ignores_auth_token_files(relative_path: str) -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", relative_path],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
