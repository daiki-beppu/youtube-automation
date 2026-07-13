"""devShell 入室時の依存同期を公開入口から検証する。"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _nix_is_available() -> bool:
    if shutil.which("nix") is None:
        return False
    probe = subprocess.run(
        ["nix", "store", "ping"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return probe.returncode == 0


def _nix_develop(
    project: Path, environment: Path, command: str = "printf shell-entered"
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(environment)
    return subprocess.run(
        ["nix", "develop", "--command", "sh", "-c", command],
        cwd=project,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.fixture
def project_copy(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    shutil.copytree(
        _REPO_ROOT,
        project,
        ignore=shutil.ignore_patterns(".git", ".venv", ".direnv", ".pytest_cache"),
    )
    return project


@pytest.mark.skipif(not _nix_is_available(), reason="a usable Nix daemon is required")
def test_nix_develop_syncs_missing_environment_and_is_quiet_on_reentry(
    project_copy: Path, tmp_path: Path
) -> None:
    environment = tmp_path / "environment"

    first = _nix_develop(
        project_copy,
        environment,
        'test -x "$UV_PROJECT_ENVIRONMENT/bin/pytest"'
        ' && "$UV_PROJECT_ENVIRONMENT/bin/pytest" --collect-only -q >/dev/null'
        " && printf shell-entered",
    )
    assert first.returncode == 0, first.stderr
    assert first.stdout == "shell-entered"
    assert (environment / "bin" / "pytest").exists()
    assert "warning: uv sync failed; dependencies may be out of date." not in first.stderr

    second = _nix_develop(project_copy, environment)
    assert second.returncode == 0, second.stderr
    assert second.stdout == "shell-entered"
    assert "Resolved " not in second.stderr
    assert "Audited " not in second.stderr


@pytest.mark.skipif(not _nix_is_available(), reason="a usable Nix daemon is required")
def test_nix_develop_warns_when_sync_fails_but_enters_shell(
    project_copy: Path, tmp_path: Path
) -> None:
    environment = tmp_path / "missing-parent" / "environment"
    environment.parent.mkdir()
    environment.parent.chmod(0o500)

    result = _nix_develop(project_copy, environment)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "shell-entered"
    assert "warning: uv sync failed; dependencies may be out of date." in result.stderr
    assert not environment.exists()
