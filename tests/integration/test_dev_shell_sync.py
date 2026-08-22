"""devShell 入室時の依存同期を公開入口から検証する。"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT, is_inside_worktree_store

_REPO_ROOT = REPO_ROOT
_PROJECT_COPY_ENTRIES = (
    ".claude",
    "LICENSE",
    "README.md",
    "docs/features.md",
    "docs/workflow-cheatsheet.md",
    "flake.nix",
    "flake.lock",
    "hatch_build.py",
    "pyproject.toml",
    "uv.lock",
    "src",
)
_BUILD_ARTIFACT_IGNORE = shutil.ignore_patterns(".pytest_cache", "__pycache__", "*.pyc")
_MAX_PROJECT_COPY_BYTES = 10 * 1024 * 1024


def _project_copy_ignore(directory: str, names: list[str]) -> set[str]:
    """ビルド生成物と worktree 置き場をコピー対象から外す。

    `.claude` を丸ごとコピーするため、規約どおり `.claude/worktrees/` に切られた
    worktree をそのまま含めるとコピーが GB 級に膨らむ。サイズ上限は `.claude` 自体の
    肥大を検出するためのものなので、上限を緩めずに worktree だけを除外する。
    """
    ignored = set(_BUILD_ARTIFACT_IGNORE(directory, names))
    ignored.update(name for name in names if is_inside_worktree_store(Path(directory) / name, _REPO_ROOT))
    return ignored


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


def _remove_test_tmp(tmp_path: Path) -> None:
    # uv creates a several-hundred-MB environment beside the project copy. Remove
    # the whole per-test root ourselves so interrupted retention cleanup cannot
    # accumulate successful runs. A test intentionally makes one parent read-only.
    for directory, _, _ in os.walk(tmp_path, topdown=False):
        directory_path = Path(directory)
        directory_path.chmod(directory_path.stat().st_mode | stat.S_IRWXU)
    shutil.rmtree(tmp_path)


@pytest.fixture
def project_copy(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    request.addfinalizer(lambda: _remove_test_tmp(tmp_path))

    project = tmp_path / "project"
    project.mkdir()
    for entry_name in _PROJECT_COPY_ENTRIES:
        source = _REPO_ROOT / entry_name
        destination = project / entry_name
        if source.is_dir():
            shutil.copytree(source, destination, ignore=_project_copy_ignore)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    return project


@pytest.mark.skipif(not _nix_is_available(), reason="a usable Nix daemon is required")
def test_nix_develop_syncs_missing_environment_and_is_quiet_on_reentry(project_copy: Path, tmp_path: Path) -> None:
    environment = tmp_path / "environment"
    project_copy_size = sum(path.stat().st_size for path in project_copy.rglob("*") if path.is_file())
    assert project_copy_size < _MAX_PROJECT_COPY_BYTES

    first = _nix_develop(
        project_copy,
        environment,
        'test -x "$UV_PROJECT_ENVIRONMENT/bin/pytest"'
        ' && "$UV_PROJECT_ENVIRONMENT/bin/pytest" --version >/dev/null'
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
def test_nix_develop_warns_when_sync_fails_but_enters_shell(project_copy: Path, tmp_path: Path) -> None:
    non_directory_parent = tmp_path / "not-a-directory"
    non_directory_parent.write_text("blocks environment creation\n", encoding="utf-8")
    environment = non_directory_parent / "environment"

    result = _nix_develop(project_copy, environment)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "shell-entered"
    assert "warning: uv sync failed; dependencies may be out of date." in result.stderr
    assert not environment.exists()
