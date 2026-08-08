from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT

SETTINGS_PATH = REPO_ROOT / ".claude" / "settings.json"
SETTINGS_TEMPLATE_PATH = REPO_ROOT / ".claude" / "settings.template.json"


def _run_git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _warning_command() -> str:
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    event_hooks = settings["hooks"]["UserPromptSubmit"]
    assert len(event_hooks) == 1
    commands = event_hooks[0]["hooks"]
    assert len(commands) == 1
    return commands[0]["command"]


def _run_warning_hook(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "-c", _warning_command()],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def main_checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "arbitrary" / "relocated-clone"
    checkout.mkdir(parents=True)
    _run_git(checkout, "init", "-b", "main")
    _run_git(checkout, "config", "user.email", "test@example.com")
    _run_git(checkout, "config", "user.name", "Test User")
    _run_git(checkout, "commit", "--allow-empty", "-m", "initial")
    return checkout


def test_warns_on_main_branch_in_main_checkout(main_checkout: Path) -> None:
    nested_directory = main_checkout / "nested" / "directory"
    nested_directory.mkdir(parents=True)

    result = _run_warning_hook(nested_directory)

    assert result.returncode == 0
    assert "main tree" in result.stdout
    assert "worktree" in result.stdout


def test_stays_silent_on_feature_branch_in_main_checkout(main_checkout: Path) -> None:
    _run_git(main_checkout, "switch", "-c", "feature/example")

    result = _run_warning_hook(main_checkout)

    assert result.returncode == 0
    assert result.stdout == ""


def test_stays_silent_in_linked_worktree(main_checkout: Path, tmp_path: Path) -> None:
    linked_worktree = tmp_path / "linked-worktree"
    _run_git(main_checkout, "switch", "--detach")
    _run_git(main_checkout, "worktree", "add", str(linked_worktree), "main")

    result = _run_warning_hook(linked_worktree)

    assert result.returncode == 0
    assert (
        subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=linked_worktree,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == "main"
    )
    assert result.stdout == ""


def test_main_tree_warning_is_not_distributed_by_settings_template() -> None:
    template = json.loads(SETTINGS_TEMPLATE_PATH.read_text(encoding="utf-8"))

    assert "UserPromptSubmit" not in template["hooks"]
