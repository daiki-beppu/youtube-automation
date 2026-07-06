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
            f'git rev-parse --git-dir >/dev/null 2>&1 && bash "{_LEFTHOOK_INSTALL_SCRIPT_PATH}"',
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


def _configure_git_identity(repo: Path) -> None:
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)


def _create_logging_lefthook(path: Path, log_path: Path) -> None:
    _create_fake_executable(
        path,
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> {log_path}\nexit 0\n",
    )


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


def _commit_file(repo: Path, name: str = "tracked.txt", *, verify: bool = True) -> subprocess.CompletedProcess[str]:
    target = repo / name
    target.write_text(target.read_text(encoding="utf-8") + "x\n" if target.exists() else "content\n", encoding="utf-8")
    subprocess.run(["git", "add", name], cwd=repo, check=True)
    command = ["git", "commit", "-m", f"test commit {name}"]
    if not verify:
        command.insert(2, "--no-verify")
    return subprocess.run(
        command,
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )


def _create_bare_remote(tmp_path: Path, repo: Path) -> Path:
    remote = tmp_path / f"{repo.name}-remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    return remote


def _push_head(repo: Path, path: str, *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "push", "origin", "HEAD:main"],
        cwd=repo,
        env={**os.environ, "PATH": path, **(extra_env or {})},
        text=True,
        capture_output=True,
        check=False,
    )


def test_dev_shell_reinstalls_lefthook_without_hiding_failures() -> None:
    flake = _read(_FLAKE_PATH)

    assert "lefthook" in flake
    assert 'bash "${./.}/.lefthook/install.sh" || exit 1' in flake
    assert 'bash "$git_root/.lefthook/install.sh"' not in flake
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
    assert (tmp_path / ".git" / "hooks" / "pre-commit").is_file()
    assert (tmp_path / ".git" / "hooks" / "pre-push").is_file()


def test_lefthook_install_script_retries_transient_force_install_failure(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_log = tmp_path / "lefthook-args.txt"
    count_file = tmp_path / "lefthook-count.txt"
    _create_fake_executable(
        bin_dir / "lefthook",
        f"""#!/usr/bin/env bash
set -eu
count=0
if [ -f {count_file} ]; then
  count="$(cat {count_file})"
fi
count="$((count + 1))"
printf '%s' "$count" > {count_file}
printf '%s\\n' "$*" >> {args_log}
if [ "$count" -eq 1 ]; then
  exit 42
fi
""",
    )

    result = _run_install_script(tmp_path, f"{bin_dir}:/usr/bin:/bin")

    assert result.returncode == 0
    assert args_log.read_text(encoding="utf-8") == "install --force\ninstall --force\n"
    assert (tmp_path / ".git" / "hooks" / "pre-commit").is_file()
    assert (tmp_path / ".git" / "hooks" / "pre-push").is_file()


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


def test_generated_pre_commit_hook_fails_closed_when_lefthook_path_is_stale(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    _configure_git_identity(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_lefthook = bin_dir / "lefthook"
    _create_fake_executable(fake_lefthook, "#!/usr/bin/env bash\nexit 0\n")

    install_result = _run_install_script(tmp_path, f"{bin_dir}:/usr/bin:/bin")
    assert install_result.returncode == 0
    fake_lefthook.unlink()

    (tmp_path / "tracked.txt").write_text("content\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    commit_result = subprocess.run(
        ["git", "commit", "-m", "test commit"],
        cwd=tmp_path,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert commit_result.returncode != 0
    assert "error: lefthook is not available in PATH; enter via nix develop or direnv." in (
        commit_result.stdout + commit_result.stderr
    )


def test_generated_pre_commit_hook_uses_installed_lefthook_path(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    _configure_git_identity(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "lefthook-calls.txt"
    _create_logging_lefthook(bin_dir / "lefthook", call_log)

    install_result = _run_install_script(tmp_path, f"{bin_dir}:/usr/bin:/bin")
    assert install_result.returncode == 0
    commit_result = _commit_file(tmp_path)

    assert commit_result.returncode == 0
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        "install --force",
        "run pre-commit",
    ]


def test_generated_pre_commit_hook_uses_path_fallback_when_installed_path_is_stale(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    _configure_git_identity(tmp_path)
    install_bin_dir = tmp_path / "install-bin"
    fallback_bin_dir = tmp_path / "fallback-bin"
    install_bin_dir.mkdir()
    fallback_bin_dir.mkdir()
    call_log = tmp_path / "lefthook-calls.txt"
    installed_lefthook = install_bin_dir / "lefthook"
    _create_logging_lefthook(installed_lefthook, call_log)

    install_result = _run_install_script(tmp_path, f"{install_bin_dir}:/usr/bin:/bin")
    assert install_result.returncode == 0
    installed_lefthook.unlink()
    _create_logging_lefthook(fallback_bin_dir / "lefthook", call_log)
    commit_result = subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "fallback commit"],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{fallback_bin_dir}:/usr/bin:/bin"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert commit_result.returncode == 0
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        "install --force",
        "run pre-commit",
    ]


def test_generated_pre_commit_hook_honors_lefthook_zero_when_lefthook_path_is_stale(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    _configure_git_identity(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_lefthook = bin_dir / "lefthook"
    _create_fake_executable(fake_lefthook, "#!/usr/bin/env bash\nexit 0\n")

    install_result = _run_install_script(tmp_path, f"{bin_dir}:/usr/bin:/bin")
    assert install_result.returncode == 0
    fake_lefthook.unlink()
    (tmp_path / "tracked.txt").write_text("content\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    commit_result = subprocess.run(
        ["git", "commit", "-m", "skip hooks"],
        cwd=tmp_path,
        env={**os.environ, "PATH": "/usr/bin:/bin", "LEFTHOOK": "0"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert commit_result.returncode == 0


def test_generated_pre_commit_hook_fails_closed_in_linked_worktree_when_lefthook_path_is_stale(
    tmp_path: Path,
) -> None:
    worktree = _create_linked_worktree_with_hook_files(tmp_path)
    _configure_git_identity(worktree)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_lefthook = bin_dir / "lefthook"
    _create_fake_executable(fake_lefthook, "#!/usr/bin/env bash\nexit 0\n")

    install_result = _run_install_script(worktree, f"{bin_dir}:/usr/bin:/bin")
    assert install_result.returncode == 0
    fake_lefthook.unlink()

    (worktree / "tracked.txt").write_text("content\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=worktree, check=True)
    commit_result = subprocess.run(
        ["git", "commit", "-m", "test commit"],
        cwd=worktree,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert commit_result.returncode != 0
    assert "error: lefthook is not available in PATH; enter via nix develop or direnv." in (
        commit_result.stdout + commit_result.stderr
    )


def test_generated_pre_push_hook_fails_closed_when_lefthook_path_is_stale(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    _configure_git_identity(repo)
    _create_bare_remote(tmp_path, repo)
    assert _commit_file(repo, verify=False).returncode == 0
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_lefthook = bin_dir / "lefthook"
    _create_fake_executable(fake_lefthook, "#!/usr/bin/env bash\nexit 0\n")

    install_result = _run_install_script(repo, f"{bin_dir}:/usr/bin:/bin")
    assert install_result.returncode == 0
    fake_lefthook.unlink()

    push_result = _push_head(repo, "/usr/bin:/bin")

    assert push_result.returncode != 0
    assert "error: lefthook is not available in PATH; enter via nix develop or direnv." in (
        push_result.stdout + push_result.stderr
    )


def test_generated_pre_push_hook_uses_installed_lefthook_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    _configure_git_identity(repo)
    _create_bare_remote(tmp_path, repo)
    assert _commit_file(repo, verify=False).returncode == 0
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "lefthook-calls.txt"
    _create_logging_lefthook(bin_dir / "lefthook", call_log)

    install_result = _run_install_script(repo, f"{bin_dir}:/usr/bin:/bin")
    assert install_result.returncode == 0
    push_result = _push_head(repo, "/usr/bin:/bin")

    assert push_result.returncode == 0
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        "install --force",
        "run pre-push origin " + str(tmp_path / "repo-remote.git"),
    ]


def test_generated_pre_push_hook_uses_path_fallback_when_installed_path_is_stale(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    _configure_git_identity(repo)
    _create_bare_remote(tmp_path, repo)
    assert _commit_file(repo, verify=False).returncode == 0
    install_bin_dir = tmp_path / "install-bin"
    fallback_bin_dir = tmp_path / "fallback-bin"
    install_bin_dir.mkdir()
    fallback_bin_dir.mkdir()
    call_log = tmp_path / "lefthook-calls.txt"
    installed_lefthook = install_bin_dir / "lefthook"
    _create_logging_lefthook(installed_lefthook, call_log)

    install_result = _run_install_script(repo, f"{install_bin_dir}:/usr/bin:/bin")
    assert install_result.returncode == 0
    installed_lefthook.unlink()
    _create_logging_lefthook(fallback_bin_dir / "lefthook", call_log)
    push_result = _push_head(repo, f"{fallback_bin_dir}:/usr/bin:/bin")

    assert push_result.returncode == 0
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        "install --force",
        "run pre-push origin " + str(tmp_path / "repo-remote.git"),
    ]


def test_generated_pre_push_hook_honors_lefthook_zero_when_lefthook_path_is_stale(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    _configure_git_identity(repo)
    _create_bare_remote(tmp_path, repo)
    assert _commit_file(repo, verify=False).returncode == 0
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_lefthook = bin_dir / "lefthook"
    _create_fake_executable(fake_lefthook, "#!/usr/bin/env bash\nexit 0\n")

    install_result = _run_install_script(repo, f"{bin_dir}:/usr/bin:/bin")
    assert install_result.returncode == 0
    fake_lefthook.unlink()
    push_result = _push_head(repo, "/usr/bin:/bin", extra_env={"LEFTHOOK": "0"})

    assert push_result.returncode == 0


def test_generated_pre_push_hook_fails_closed_in_linked_worktree_when_lefthook_path_is_stale(
    tmp_path: Path,
) -> None:
    worktree = _create_linked_worktree_with_hook_files(tmp_path)
    _configure_git_identity(worktree)
    _create_bare_remote(tmp_path, worktree)
    assert _commit_file(worktree, verify=False).returncode == 0
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_lefthook = bin_dir / "lefthook"
    _create_fake_executable(fake_lefthook, "#!/usr/bin/env bash\nexit 0\n")

    install_result = _run_install_script(worktree, f"{bin_dir}:/usr/bin:/bin")
    assert install_result.returncode == 0
    fake_lefthook.unlink()
    push_result = _push_head(worktree, "/usr/bin:/bin")

    assert push_result.returncode != 0
    assert "error: lefthook is not available in PATH; enter via nix develop or direnv." in (
        push_result.stdout + push_result.stderr
    )


def test_generated_pre_push_hook_uses_path_fallback_in_linked_worktree_when_installed_path_is_stale(
    tmp_path: Path,
) -> None:
    worktree = _create_linked_worktree_with_hook_files(tmp_path)
    _configure_git_identity(worktree)
    _create_bare_remote(tmp_path, worktree)
    assert _commit_file(worktree, verify=False).returncode == 0
    install_bin_dir = tmp_path / "install-bin"
    fallback_bin_dir = tmp_path / "fallback-bin"
    install_bin_dir.mkdir()
    fallback_bin_dir.mkdir()
    call_log = tmp_path / "lefthook-calls.txt"
    installed_lefthook = install_bin_dir / "lefthook"
    _create_logging_lefthook(installed_lefthook, call_log)

    install_result = _run_install_script(worktree, f"{install_bin_dir}:/usr/bin:/bin")
    assert install_result.returncode == 0
    installed_lefthook.unlink()
    _create_logging_lefthook(fallback_bin_dir / "lefthook", call_log)
    push_result = _push_head(worktree, f"{fallback_bin_dir}:/usr/bin:/bin")

    assert push_result.returncode == 0
    assert (
        "run pre-push origin " + str(tmp_path / "linked-worktree-remote.git")
        in call_log.read_text(encoding="utf-8").splitlines()
    )


def test_lefthook_install_script_fails_when_hook_path_is_not_a_file(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / ".git" / "hooks" / "pre-commit").mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _create_fake_executable(bin_dir / "lefthook", "#!/usr/bin/env bash\nexit 0\n")

    result = _run_install_script(tmp_path, f"{bin_dir}:/usr/bin:/bin")

    assert result.returncode == 1
    assert "cannot install pre-commit hook" in result.stderr
    assert not (tmp_path / ".git" / "hooks" / "pre-push").exists()


def test_lefthook_install_script_fails_when_force_install_fails(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_log = tmp_path / "lefthook-args.txt"
    _create_fake_executable(
        bin_dir / "lefthook",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> {args_log}\nexit 42\n",
    )

    result = _run_install_script(tmp_path, f"{bin_dir}:/usr/bin:/bin")

    assert result.returncode == 1
    assert args_log.read_text(encoding="utf-8") == ("install --force\ninstall --force\ninstall --force\n")
    assert (
        "error: lefthook install failed; run 'nix develop --command bash .lefthook/install.sh' after fixing the error."
    ) in result.stderr


def test_lefthook_config_documents_install_script_entrypoint() -> None:
    config = _read(_LEFTHOOK_CONFIG_PATH)

    assert ".lefthook/install.sh" in config
    assert "nix develop --command bash .lefthook/install.sh" in config
    assert "nix develop --command lefthook install --force" not in config


def test_docs_cover_parent_worktree_diagnostics_and_reinstall() -> None:
    development = _read(_DEVELOPMENT_DOC_PATH)
    takt_operations = _read(_TAKT_OPERATIONS_DOC_PATH)
    claude = _read(_CLAUDE_PATH)
    agents = _read(_AGENTS_PATH)

    for required in (
        "command -v lefthook && lefthook version",
        "nix develop --command bash .lefthook/install.sh",
        "Can't find lefthook in PATH",
    ):
        assert required in development

    for required in (
        ".lefthook/install.sh",
        "command -v lefthook && lefthook version",
    ):
        assert required in takt_operations

    assert "nix develop --command bash .lefthook/install.sh" in agents
    assert ".lefthook/install.sh" in claude
    assert "nix develop --command lefthook install --force" not in development
    assert "nix develop --command lefthook install --force" not in takt_operations
    assert "nix develop --command lefthook install --force" not in agents
