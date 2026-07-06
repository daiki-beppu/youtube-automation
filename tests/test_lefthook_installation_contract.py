from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FLAKE_PATH = _REPO_ROOT / "flake.nix"
_LEFTHOOK_INSTALL_SCRIPT_PATH = _REPO_ROOT / ".lefthook" / "install.sh"
_LEFTHOOK_CONFIG_PATH = _REPO_ROOT / "lefthook.yml"
_DEVELOPMENT_DOC_PATH = _REPO_ROOT / "docs" / "development.md"
_TAKT_OPERATIONS_DOC_PATH = _REPO_ROOT / "docs" / "takt-operations.md"
_CLAUDE_PATH = _REPO_ROOT / "CLAUDE.md"
_AGENTS_PATH = _REPO_ROOT / "AGENTS.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run_install_script(workdir: Path, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_LEFTHOOK_INSTALL_SCRIPT_PATH)],
        cwd=workdir,
        env={**os.environ, "PATH": path},
        text=True,
        capture_output=True,
        check=False,
    )


def _run_shell_hook_install_entrypoint(workdir: Path, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-lc",
            'git_root="$(git rev-parse --show-toplevel 2>/dev/null)" && bash "$git_root/.lefthook/install.sh"',
        ],
        cwd=workdir,
        env={**os.environ, "PATH": path},
        text=True,
        capture_output=True,
        check=False,
    )


def _create_fake_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _create_linked_worktree_with_hook_files(tmp_path: Path) -> Path:
    parent = tmp_path / "parent-checkout"
    worktree = tmp_path / "linked-worktree"
    subprocess.run(["git", "init", str(parent)], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(parent), "worktree", "add", "--orphan", str(worktree)],
        check=True,
        capture_output=True,
        text=True,
    )
    (worktree / ".lefthook").mkdir()
    (worktree / ".lefthook" / "install.sh").write_text(
        _read(_LEFTHOOK_INSTALL_SCRIPT_PATH),
        encoding="utf-8",
    )
    (worktree / "lefthook.yml").write_text(_read(_LEFTHOOK_CONFIG_PATH), encoding="utf-8")
    return worktree


def test_dev_shell_reinstalls_lefthook_without_hiding_failures() -> None:
    flake = _read(_FLAKE_PATH)

    assert "lefthook" in flake
    assert '.lefthook/install.sh" || exit 1' in flake
    assert "lefthook install >/dev/null 2>&1 || true" not in flake
    assert "exit 1" in flake


def test_lefthook_install_script_noops_outside_git_repo(tmp_path: Path) -> None:
    result = _run_install_script(tmp_path, "/usr/bin:/bin")

    assert result.returncode == 0
    assert result.stderr == ""


def test_lefthook_install_script_fails_when_lefthook_is_missing(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)

    result = _run_install_script(tmp_path, "/usr/bin:/bin")

    assert result.returncode == 1
    assert "error: lefthook is not available in PATH; enter via nix develop or direnv." in result.stderr


def test_lefthook_install_script_runs_force_install(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_log = tmp_path / "lefthook-args.txt"
    _create_fake_executable(
        bin_dir / "lefthook",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > {args_log}\n",
    )

    result = _run_install_script(tmp_path, f"{bin_dir}:/usr/bin:/bin")

    assert result.returncode == 0
    assert args_log.read_text(encoding="utf-8") == "install --force\n"


def test_shell_hook_entrypoint_runs_force_install_from_linked_worktree(tmp_path: Path) -> None:
    worktree = _create_linked_worktree_with_hook_files(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "lefthook-call.txt"
    _create_fake_executable(
        bin_dir / "lefthook",
        f'#!/usr/bin/env bash\nprintf \'cwd=%s\\nargs=%s\\n\' "$PWD" "$*" > {call_log}\n',
    )

    result = _run_shell_hook_install_entrypoint(worktree, f"{bin_dir}:/usr/bin:/bin")

    assert result.returncode == 0
    assert call_log.read_text(encoding="utf-8") == f"cwd={worktree}\nargs=install --force\n"


def test_shell_hook_entrypoint_fails_loudly_in_linked_worktree_when_lefthook_is_missing(
    tmp_path: Path,
) -> None:
    worktree = _create_linked_worktree_with_hook_files(tmp_path)

    result = _run_shell_hook_install_entrypoint(worktree, "/usr/bin:/bin")

    assert result.returncode == 1
    assert "error: lefthook is not available in PATH; enter via nix develop or direnv." in result.stderr


def test_lefthook_install_script_fails_when_force_install_fails(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_log = tmp_path / "lefthook-args.txt"
    _create_fake_executable(
        bin_dir / "lefthook",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > {args_log}\nexit 42\n",
    )

    result = _run_install_script(tmp_path, f"{bin_dir}:/usr/bin:/bin")

    assert result.returncode == 1
    assert args_log.read_text(encoding="utf-8") == "install --force\n"
    assert (
        "error: lefthook install failed; run 'nix develop --command lefthook install --force' after fixing the error."
    ) in result.stderr


def test_lefthook_config_documents_force_reinstall_entrypoint() -> None:
    config = _read(_LEFTHOOK_CONFIG_PATH)

    assert "lefthook install --force" in config
    assert "nix develop --command lefthook install --force" in config


def test_docs_cover_parent_worktree_diagnostics_and_reinstall() -> None:
    development = _read(_DEVELOPMENT_DOC_PATH)
    takt_operations = _read(_TAKT_OPERATIONS_DOC_PATH)
    claude = _read(_CLAUDE_PATH)
    agents = _read(_AGENTS_PATH)

    for required in (
        "親 checkout / worktree",
        "command -v lefthook && lefthook version",
        "nix develop --command lefthook install --force",
        "Can't find lefthook in PATH",
        "|| true",
    ):
        assert required in development

    for required in (
        "worktree で commit / push",
        "lefthook install --force",
        "command -v lefthook && lefthook version",
    ):
        assert required in takt_operations

    assert "対象 worktree で `nix develop`" in claude
    assert "対象 checkout" in agents
    assert "nix develop --command lefthook install --force" in agents
