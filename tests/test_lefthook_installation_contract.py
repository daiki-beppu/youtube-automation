from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FLAKE_PATH = _REPO_ROOT / "flake.nix"
_LEFTHOOK_INSTALL_SCRIPT_PATH = _REPO_ROOT / ".lefthook" / "install.sh"
_WORKTREE_SETUP_SCRIPT_PATH = _REPO_ROOT / ".lefthook" / "setup-worktree.sh"
_SYNC_DEPS_SCRIPT_PATH = _REPO_ROOT / ".lefthook" / "sync-deps.sh"
_ENVRC_PATH = _REPO_ROOT / ".envrc"
_LITE_WORKFLOW_PATH = _REPO_ROOT / ".takt" / "workflows" / "lite.yaml"
_LEFTHOOK_CONFIG_PATH = _REPO_ROOT / "lefthook.yml"
_DEVELOPMENT_DOC_PATH = _REPO_ROOT / "docs" / "development.md"
_TAKT_OPERATIONS_DOC_PATH = _REPO_ROOT / "docs" / "takt-operations.md"
_CLAUDE_PATH = _REPO_ROOT / "CLAUDE.md"
_AGENTS_PATH = _REPO_ROOT / "AGENTS.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _subprocess_env(**overrides: str) -> dict[str, str]:
    # 契約テストの前提となる環境変数はテスト自身が固定する。takt runtime が全 worker へ
    # 注入する YOUTUBE_AUTOMATION_SKIP_LEFTHOOK が subprocess へリークすると install 実行を
    # 期待するテストが skip 分岐に入って失敗するため、必ず除去する（issue #2101）。
    # skip 挙動を検証するテストは overrides で明示的に設定する
    env = {key: value for key, value in os.environ.items() if key != "YOUTUBE_AUTOMATION_SKIP_LEFTHOOK"}
    env.update(overrides)
    return env


def _run_install_script(workdir: Path, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_LEFTHOOK_INSTALL_SCRIPT_PATH)],
        cwd=workdir,
        env=_subprocess_env(PATH=path),
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
        env=_subprocess_env(PATH=path),
        text=True,
        capture_output=True,
        check=False,
    )


def _create_fake_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_worktree_setup(workdir: Path, path: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_WORKTREE_SETUP_SCRIPT_PATH), *args],
        cwd=workdir,
        env=_subprocess_env(PATH=path),
        text=True,
        capture_output=True,
        check=False,
    )


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
    (worktree / ".lefthook" / "sync-deps.sh").write_text(
        _read(_SYNC_DEPS_SCRIPT_PATH),
        encoding="utf-8",
    )
    (worktree / "lefthook.yml").write_text(_read(_LEFTHOOK_CONFIG_PATH), encoding="utf-8")
    return worktree


def _create_parent_checkout_with_hook_files(tmp_path: Path) -> Path:
    parent = tmp_path / "parent-checkout"
    subprocess.run(["git", "init", str(parent)], check=True, capture_output=True, text=True)
    (parent / ".lefthook").mkdir()
    (parent / ".lefthook" / "install.sh").write_text(
        _read(_LEFTHOOK_INSTALL_SCRIPT_PATH),
        encoding="utf-8",
    )
    (parent / ".lefthook" / "sync-deps.sh").write_text(
        _read(_SYNC_DEPS_SCRIPT_PATH),
        encoding="utf-8",
    )
    (parent / "lefthook.yml").write_text(_read(_LEFTHOOK_CONFIG_PATH), encoding="utf-8")
    return parent


def _write_sync_deps_script(checkout: Path) -> None:
    lefthook_dir = checkout / ".lefthook"
    lefthook_dir.mkdir(exist_ok=True)
    (lefthook_dir / "sync-deps.sh").write_text(_read(_SYNC_DEPS_SCRIPT_PATH), encoding="utf-8")


def _run_sync_deps(workdir: Path, path: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_SYNC_DEPS_SCRIPT_PATH), *args],
        cwd=workdir,
        env={**os.environ, "PATH": path},
        text=True,
        capture_output=True,
        check=False,
    )


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
        env=_subprocess_env(PATH=path, **(extra_env or {})),
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


def test_dev_shell_skips_lefthook_install_when_skip_env_is_set() -> None:
    # sandbox 化された takt worker（hooks を書き込めない）向けの安全なスキップ分岐
    # （issue #1999）。既定では従来どおり fail-closed（|| exit 1）のまま
    flake = _read(_FLAKE_PATH)

    assert "YOUTUBE_AUTOMATION_SKIP_LEFTHOOK" in flake


def test_lefthook_install_script_skips_when_skip_env_is_set(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)

    # lefthook が PATH に無くても skip が優先され成功終了する
    result = subprocess.run(
        ["bash", str(_LEFTHOOK_INSTALL_SCRIPT_PATH)],
        cwd=tmp_path,
        env=_subprocess_env(PATH="/usr/bin:/bin", YOUTUBE_AUTOMATION_SKIP_LEFTHOOK="1"),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1" in result.stderr
    hooks_dir = tmp_path / ".git" / "hooks"
    assert not (hooks_dir / "pre-commit").exists()
    assert not (hooks_dir / "pre-push").exists()


def test_takt_runtime_prepare_injects_sandbox_safe_environment(tmp_path: Path) -> None:
    # takt の runtime.prepare が全 worker へ worktree ローカルの XDG_DATA_HOME と
    # lefthook skip を注入する配線契約（issue #1999）
    takt_config = _read(_REPO_ROOT / ".takt" / "config.yaml")
    assert ".takt/runtime-prepare.sh" in takt_config

    runtime_root = tmp_path / "runtime"
    result = subprocess.run(
        ["bash", str(_REPO_ROOT / ".takt" / "runtime-prepare.sh")],
        env=_subprocess_env(TAKT_RUNTIME_ROOT=str(runtime_root)),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert f"XDG_DATA_HOME={runtime_root}/data" in lines
    assert "YOUTUBE_AUTOMATION_SKIP_LEFTHOOK=1" in lines


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
        env=_subprocess_env(PATH="/usr/bin:/bin"),
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
        env=_subprocess_env(PATH=f"{fallback_bin_dir}:/usr/bin:/bin"),
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
        env=_subprocess_env(PATH="/usr/bin:/bin", LEFTHOOK="0"),
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
        env=_subprocess_env(PATH="/usr/bin:/bin"),
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


def test_worktree_setup_uses_direnv_allow_and_exec_with_forwarded_arguments(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    _write_sync_deps_script(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "direnv-calls.txt"
    _create_fake_executable(
        bin_dir / "direnv",
        f"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "{call_log}"
if [ "$1" = "allow" ]; then
  exit 0
fi
shift 2
exec "$@"
""",
    )

    result = _run_worktree_setup(
        tmp_path,
        f"{bin_dir}:/usr/bin:/bin",
        "sh",
        "-c",
        "printf forwarded",
    )

    assert result.returncode == 0
    assert result.stdout == "forwarded"
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        f"allow {tmp_path}",
        f"exec {tmp_path} bash {tmp_path}/.lefthook/sync-deps.sh sh -c printf forwarded",
    ]


def test_worktree_setup_resolves_checkout_root_from_subdirectory(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    nested = tmp_path / "nested" / "directory"
    nested.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "direnv-calls.txt"
    _create_fake_executable(
        bin_dir / "direnv",
        f'#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "{call_log}"\nexit 0\n',
    )

    result = _run_worktree_setup(nested, f"{bin_dir}:/usr/bin:/bin")

    assert result.returncode == 0
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        f"allow {tmp_path}",
        f"exec {tmp_path} bash {tmp_path}/.lefthook/sync-deps.sh bash {tmp_path}/.lefthook/install.sh",
    ]


def test_worktree_setup_falls_back_to_nix_and_runs_default_install(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    _write_sync_deps_script(tmp_path)
    install_log = tmp_path / "install-ran.txt"
    _create_fake_executable(
        tmp_path / ".lefthook" / "install.sh",
        f'#!/usr/bin/env bash\nprintf installed > "{install_log}"\n',
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    nix_log = tmp_path / "nix-call.txt"
    _create_fake_executable(
        bin_dir / "nix",
        f"""#!/usr/bin/env bash
printf '%s\n' "$*" > "{nix_log}"
shift 3
exec "$@"
""",
    )

    result = _run_worktree_setup(tmp_path, f"{bin_dir}:/usr/bin:/bin")

    assert result.returncode == 0
    assert nix_log.read_text(encoding="utf-8") == (
        f"develop {tmp_path} --command bash {tmp_path}/.lefthook/sync-deps.sh bash {tmp_path}/.lefthook/install.sh\n"
    )
    assert install_log.read_text(encoding="utf-8") == "installed"


def _assert_setup_supplies_dev_shell_tools_and_commit_hook(checkout: Path, tmp_path: Path) -> None:
    _configure_git_identity(checkout)
    hook_log = tmp_path / f"{checkout.name}-hook-ran.txt"
    (checkout / "flake.nix").write_text(_read(_FLAKE_PATH), encoding="utf-8")
    (checkout / "flake.lock").write_text(_read(_REPO_ROOT / "flake.lock"), encoding="utf-8")
    (checkout / "lefthook.yml").write_text(
        f"pre-commit:\n  commands:\n    prove-hook-runs:\n      run: printf ran > {hook_log}\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=checkout, check=True)
    subprocess.run(
        ["git", "commit", "--no-verify", "-m", "prepare dev shell fixture"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    )

    setup_result = _run_worktree_setup(
        checkout,
        "/nix/var/nix/profiles/default/bin:/usr/bin:/bin",
        "sh",
        "-c",
        "command -v lefthook && command -v uv",
    )
    commit_result = _commit_file(checkout)

    assert setup_result.returncode == 0
    tool_paths = setup_result.stdout.splitlines()[-2:]
    assert all(path.startswith("/nix/store/") for path in tool_paths)
    assert tool_paths[0].endswith("/bin/lefthook")
    assert tool_paths[1].endswith("/bin/uv")
    assert commit_result.returncode == 0
    assert hook_log.read_text(encoding="utf-8") == "ran"


def test_parent_checkout_setup_supplies_dev_shell_tools_and_commit_hook(tmp_path: Path) -> None:
    parent = _create_parent_checkout_with_hook_files(tmp_path)

    _assert_setup_supplies_dev_shell_tools_and_commit_hook(parent, tmp_path)


def test_linked_worktree_setup_supplies_dev_shell_tools_and_commit_hook(tmp_path: Path) -> None:
    worktree = _create_linked_worktree_with_hook_files(tmp_path)

    _assert_setup_supplies_dev_shell_tools_and_commit_hook(worktree, tmp_path)


def test_worktree_setup_falls_back_to_nix_when_direnv_allow_fails(tmp_path: Path) -> None:
    # sandbox 化された環境では direnv の allow ストア（$XDG_DATA_HOME/direnv/allow）へ
    # 書込みできず direnv allow が失敗する。hard fail で反復停滞せず nix develop へ
    # フォールバックする契約（issue #1999）
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    _write_sync_deps_script(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _create_fake_executable(bin_dir / "direnv", "#!/usr/bin/env bash\nexit 23\n")
    nix_log = tmp_path / "nix-call.txt"
    _create_fake_executable(
        bin_dir / "nix",
        f"""#!/usr/bin/env bash
printf '%s\n' "$*" > "{nix_log}"
shift 3
exec "$@"
""",
    )

    result = _run_worktree_setup(tmp_path, f"{bin_dir}:/usr/bin:/bin", "sh", "-c", "printf ran")

    assert result.returncode == 0
    assert result.stdout == "ran"
    assert "direnv allow に失敗しました" in result.stderr
    assert nix_log.read_text(encoding="utf-8") == (
        f"develop {tmp_path} --command bash {tmp_path}/.lefthook/sync-deps.sh sh -c printf ran\n"
    )


def test_worktree_setup_fails_when_direnv_allow_fails_without_nix(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _create_fake_executable(bin_dir / "direnv", "#!/usr/bin/env bash\nexit 23\n")

    result = _run_worktree_setup(tmp_path, f"{bin_dir}:/usr/bin:/bin", "sh", "-c", "exit 0")

    assert result.returncode == 1
    assert "direnv allow に失敗しました" in result.stderr
    assert "error: neither direnv nor nix is available in PATH." in result.stderr


def test_worktree_setup_fails_outside_git_checkout(tmp_path: Path) -> None:
    result = _run_worktree_setup(tmp_path, "/usr/bin:/bin")

    assert result.returncode == 1
    assert result.stderr == "error: run this script from a Git checkout or worktree.\n"


def test_worktree_setup_fails_when_no_environment_loader_is_available(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)

    result = _run_worktree_setup(tmp_path, "/usr/bin:/bin")

    assert result.returncode == 1
    assert result.stderr == "error: neither direnv nor nix is available in PATH.\n"


def test_worktree_setup_wraps_commands_with_fail_closed_dependency_sync() -> None:
    # explicit setup 経路は sync-deps.sh 経由で依存同期を fail-closed 実行する
    # （issue #2125）。対話 shell（shellHook）の warning 継続とは経路分離
    setup = _read(_WORKTREE_SETUP_SCRIPT_PATH)

    assert ".lefthook/sync-deps.sh" in setup


def test_interactive_shell_hook_keeps_dependency_sync_warning_open() -> None:
    # 対話入場（direnv / nix develop）は sync 失敗でも入場を継続する方針を維持
    # （issue #2125 のスコープは explicit setup 経路のみ）
    flake = _read(_FLAKE_PATH)

    assert 'uv sync --quiet || echo "warning: uv sync failed' in flake


def test_sync_deps_fails_closed_when_uv_sync_fails(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0"\n', encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _create_fake_executable(bin_dir / "uv", "#!/usr/bin/env bash\nexit 1\n")
    marker = tmp_path / "command-ran.txt"

    result = _run_sync_deps(
        tmp_path,
        f"{bin_dir}:/usr/bin:/bin",
        "sh",
        "-c",
        f"printf ran > {marker}",
    )

    assert result.returncode != 0
    assert not marker.exists()
    assert "error: uv sync failed" in result.stderr


def test_sync_deps_runs_command_after_successful_sync(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0"\n', encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_log = tmp_path / "uv-args.txt"
    _create_fake_executable(
        bin_dir / "uv",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> {uv_log}\nexit 0\n",
    )

    result = _run_sync_deps(tmp_path, f"{bin_dir}:/usr/bin:/bin", "sh", "-c", "printf forwarded")

    assert result.returncode == 0
    assert result.stdout == "forwarded"
    assert uv_log.read_text(encoding="utf-8") == "sync --quiet\n"


def test_sync_deps_skips_sync_when_pyproject_is_missing(tmp_path: Path) -> None:
    # pyproject.toml の無い checkout（fixture 等）では同期対象が無いため、
    # uv が PATH に無くてもコマンドをそのまま実行する
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)

    result = _run_sync_deps(tmp_path, "/usr/bin:/bin", "sh", "-c", "printf forwarded")

    assert result.returncode == 0
    assert result.stdout == "forwarded"


def test_sync_deps_fails_when_uv_is_missing_with_pyproject(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0"\n', encoding="utf-8")

    result = _run_sync_deps(tmp_path, "/usr/bin:/bin", "sh", "-c", "printf forwarded")

    assert result.returncode == 1
    assert "error: uv is not available in PATH; enter via nix develop or direnv." in result.stderr


def test_worktree_setup_fails_closed_when_dependency_sync_fails(tmp_path: Path) -> None:
    # issue #2125 要件 1: 失敗する uv で explicit setup 経路を通すと全体が exit 非 0
    # になり、後続コマンドは実行されない
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    _write_sync_deps_script(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0"\n', encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _create_fake_executable(
        bin_dir / "direnv",
        """#!/usr/bin/env bash
if [ "$1" = "allow" ]; then
  exit 0
fi
shift 2
exec "$@"
""",
    )
    _create_fake_executable(bin_dir / "uv", "#!/usr/bin/env bash\nexit 1\n")
    marker = tmp_path / "command-ran.txt"

    result = _run_worktree_setup(
        tmp_path,
        f"{bin_dir}:/usr/bin:/bin",
        "sh",
        "-c",
        f"printf ran > {marker}",
    )

    assert result.returncode != 0
    assert not marker.exists()
    assert "error: uv sync failed" in result.stderr


def test_worktree_environment_contract_is_wired_into_lite_steps_and_docs() -> None:
    envrc = _read(_ENVRC_PATH)
    # nix-direnv を version + SRI hash 固定でブートストラップし（issue #2097）、
    # 最終ディレクティブは従来どおり use flake であること
    assert 'source_url "https://raw.githubusercontent.com/nix-community/nix-direnv/' in envrc
    assert '" "sha256-' in envrc
    assert "nix_direnv_version" in envrc
    assert envrc.rstrip().splitlines()[-1] == "use flake"
    workflow = _read(_LITE_WORKFLOW_PATH)
    setup_instruction = "最初に `bash .lefthook/setup-worktree.sh` を実行"
    wrapped_command_instruction = "`bash .lefthook/setup-worktree.sh <command> [args...]` 経由"
    assert workflow.count(setup_instruction) == 3
    assert workflow.count(wrapped_command_instruction) == 3

    for document in (_DEVELOPMENT_DOC_PATH, _TAKT_OPERATIONS_DOC_PATH, _CLAUDE_PATH):
        content = _read(document)
        assert "bash .lefthook/setup-worktree.sh" in content
        assert ".envrc" in content


def test_direnv_cache_is_gitignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", ".direnv/cache"],
        cwd=_REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ".direnv/cache\n"


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
