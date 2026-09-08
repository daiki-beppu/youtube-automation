"""Exercise output suppression and exit codes with real pytest subprocesses."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT

WRAPPER = REPO_ROOT / ".claude/skills/automation/references/pytest-quiet.sh"


@pytest.fixture
def wrapper_environment(tmp_path: Path) -> dict[str, str]:
    # Replace only uv's environment selection; run the real installed pytest.
    launcher = tmp_path / "uv"
    launcher.write_text(
        '#!/bin/sh\n[ "$1" = run ] && [ "$2" = pytest ] || exit 99\n'
        f'shift 2\nexec {shlex.quote(sys.executable)} -m pytest "$@"\n'
    )
    launcher.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "TMPDIR": str(tmp_path),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTEST_ADDOPTS": "",
        "PYTEST_PLUGINS": "",
    }


@pytest.mark.parametrize(
    ("source", "arguments", "expected_status", "diagnostic"),
    [
        ('def test_ok():\n    print("hidden success log")\n', ["-s"], 0, ""),
        (
            'def test_failure():\n    print("failure details")\n    assert False\n',
            [],
            1,
            "failure details",
        ),
        ("raise RuntimeError('collection details')\n", [], 2, "collection details"),
        ("", ["--nonexistent-option"], 4, "unrecognized arguments"),
        ("", [], 5, "no tests ran"),
    ],
)
def test_output_and_exit_status(
    tmp_path: Path,
    wrapper_environment: dict[str, str],
    source: str,
    arguments: list[str],
    expected_status: int,
    diagnostic: str,
) -> None:
    target = tmp_path / "test example.py"
    target.write_text(source)
    result = subprocess.run(
        ["bash", str(WRAPPER), *arguments, str(target)],
        cwd=tmp_path,
        env=wrapper_environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == expected_status
    if expected_status == 0:
        assert result.stdout.startswith("pytest: success (exit 0, ")
        assert len(result.stdout.splitlines()) == 1
        assert "hidden success log" not in result.stdout
    else:
        assert diagnostic in result.stdout
        assert "pytest: success" not in result.stdout
    assert result.stderr == ""
    assert not list(tmp_path.glob("pytest-quiet.*"))


def test_help_is_visible(tmp_path: Path, wrapper_environment: dict[str, str]) -> None:
    result = subprocess.run(
        ["bash", str(WRAPPER), "--help"],
        cwd=tmp_path,
        env=wrapper_environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "--collect-only" in result.stdout
    assert "pytest: success" not in result.stdout
