"""yt-preflight（cli/preflight.py）の検査・分類・read-only 保証のテスト（#2124）。"""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from youtube_automation.cli import preflight
from youtube_automation.cli.preflight import (
    KEY_CHECKOUT_KIND,
    KEY_GIT_COMMIT_IDENTITY,
    KEY_HOOK_POLICY,
    KEY_LOCK_DRIFT,
    KEY_NIX_EVAL,
    SKIP_LEFTHOOK_ENV,
    CheckResult,
    check_checkout_kind,
    check_git_commit_identity,
    check_hook_policy,
    check_lock_drift,
    check_nix_eval,
    format_report,
    run_checks,
)

_SECRET_NAME = "Secret Person"
_SECRET_EMAIL = "secret-identity@example.com"


def _isolated_env(tmp_path: Path, *, with_identity: bool = False, path: str | None = None) -> dict[str, str]:
    """global / system gitconfig と identity 自動推測を遮断した環境を作る。"""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": path if path is not None else os.environ["PATH"],
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg-config"),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        # hostname からの identity 自動推測を無効化し、identity 欠落を決定的に再現する
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "user.useConfigOnly",
        "GIT_CONFIG_VALUE_0": "true",
    }
    if with_identity:
        env.update(
            {
                "GIT_AUTHOR_NAME": _SECRET_NAME,
                "GIT_AUTHOR_EMAIL": _SECRET_EMAIL,
                "GIT_COMMITTER_NAME": _SECRET_NAME,
                "GIT_COMMITTER_EMAIL": _SECRET_EMAIL,
            }
        )
    return env


def _init_repo(tmp_path: Path, env: Mapping[str, str], name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "--initial-branch=main", str(repo)], env=dict(env), check=True, capture_output=True)
    return repo


def _commit_initial(repo: Path, env: Mapping[str, str]) -> None:
    (repo / "README.md").write_text("preflight fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, env=dict(env), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, env=dict(env), check=True, capture_output=True)


def _write_stub(bin_dir: Path, name: str, script: str) -> None:
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / name
    stub.write_text(script, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


_NIX_OK_STUB = """#!/usr/bin/env bash
if [[ "$*" == *"builtins.currentSystem"* ]]; then
  printf 'x86_64-linux'
  exit 0
fi
printf '/nix/store/fake-devshell.drv'
exit 0
"""

_UV_OK_STUB = """#!/usr/bin/env bash
exit 0
"""

_UV_DRIFT_STUB = """#!/usr/bin/env bash
exit 2
"""


def _stubbed_path(tmp_path: Path, *, uv_stub: str = _UV_OK_STUB, nix_stub: str = _NIX_OK_STUB) -> str:
    bin_dir = tmp_path / "stub-bin"
    _write_stub(bin_dir, "uv", uv_stub)
    _write_stub(bin_dir, "nix", nix_stub)
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


# --- git_commit_identity ---


def test_git_identity_fails_in_isolated_xdg_without_identity(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    repo = _init_repo(tmp_path, env)

    result = check_git_commit_identity(repo, env)

    assert result.key == KEY_GIT_COMMIT_IDENTITY
    assert not result.ok


def test_git_identity_passes_and_never_leaks_identity_values(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path, with_identity=True)
    repo = _init_repo(tmp_path, env)

    result = check_git_commit_identity(repo, env)

    assert result.ok
    report = format_report([result])
    assert _SECRET_NAME not in report
    assert _SECRET_EMAIL not in report


# --- hook_policy ---


def test_hook_policy_fails_when_hooks_missing_without_skip_env(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    repo = _init_repo(tmp_path, env)

    result = check_hook_policy(repo, env)

    assert result.key == KEY_HOOK_POLICY
    assert not result.ok


def test_hook_policy_passes_with_explicit_skip_env(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    env[SKIP_LEFTHOOK_ENV] = "1"
    repo = _init_repo(tmp_path, env)

    result = check_hook_policy(repo, env)

    assert result.ok
    assert SKIP_LEFTHOOK_ENV in result.detail


def test_hook_policy_passes_when_lefthook_hooks_are_installed(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    repo = _init_repo(tmp_path, env)
    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    for hook_name in ("pre-commit", "pre-push"):
        (hooks_dir / hook_name).write_text("#!/usr/bin/env bash\nexec lefthook run\n", encoding="utf-8")

    result = check_hook_policy(repo, env)

    assert result.ok


def test_hook_policy_fails_when_hook_exists_but_is_not_lefthook(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    repo = _init_repo(tmp_path, env)
    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    for hook_name in ("pre-commit", "pre-push"):
        (hooks_dir / hook_name).write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    result = check_hook_policy(repo, env)

    assert not result.ok


# --- checkout_kind ---


def test_checkout_kind_classifies_normal_checkout(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    repo = _init_repo(tmp_path, env)

    result = check_checkout_kind(repo, env)

    assert result.key == KEY_CHECKOUT_KIND
    assert result.ok
    assert result.detail == "通常 checkout"


def test_checkout_kind_classifies_linked_worktree(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path, with_identity=True)
    repo = _init_repo(tmp_path, env)
    _commit_initial(repo, env)
    worktree = tmp_path / "linked-worktree"
    subprocess.run(
        ["git", "worktree", "add", str(worktree), "-b", "wt-branch"],
        cwd=repo,
        env=dict(env),
        check=True,
        capture_output=True,
    )

    result = check_checkout_kind(worktree, env)

    assert result.ok
    assert result.detail == "linked worktree"


def test_checkout_kind_classifies_takt_clone_via_runtime_env(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    repo = _init_repo(tmp_path, env)
    env["TAKT_RUNTIME_ROOT"] = str(repo / ".takt" / ".runtime")

    result = check_checkout_kind(repo, env)

    assert result.ok
    assert result.detail == "takt 管理 clone"


def test_checkout_kind_fails_outside_git_checkout(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path)
    outside = tmp_path / "not-a-repo"
    outside.mkdir()

    result = check_checkout_kind(outside, env)

    assert not result.ok


# --- lock_drift ---


def test_lock_drift_passes_when_uv_lock_check_succeeds(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path, path=_stubbed_path(tmp_path))
    repo = _init_repo(tmp_path, env)

    result = check_lock_drift(repo, env)

    assert result.key == KEY_LOCK_DRIFT
    assert result.ok


def test_lock_drift_fails_when_uv_lock_check_reports_drift(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path, path=_stubbed_path(tmp_path, uv_stub=_UV_DRIFT_STUB))
    repo = _init_repo(tmp_path, env)

    result = check_lock_drift(repo, env)

    assert not result.ok


def test_lock_drift_fails_when_uv_is_missing(tmp_path: Path) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    repo = _init_repo(tmp_path, _isolated_env(tmp_path))
    env = _isolated_env(tmp_path, path=str(empty_bin))

    result = check_lock_drift(repo, env)

    assert not result.ok
    assert "uv" in result.detail


# --- nix_eval ---


def test_nix_eval_passes_with_evaluable_flake(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path, path=_stubbed_path(tmp_path))
    repo = _init_repo(tmp_path, env)

    result = check_nix_eval(repo, env)

    assert result.key == KEY_NIX_EVAL
    assert result.ok


def test_nix_eval_fails_when_nix_is_missing(tmp_path: Path) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    repo = _init_repo(tmp_path, _isolated_env(tmp_path))
    env = _isolated_env(tmp_path, path=str(empty_bin))

    result = check_nix_eval(repo, env)

    assert not result.ok
    assert "nix" in result.detail


def test_nix_eval_fails_when_flake_is_not_evaluable(tmp_path: Path) -> None:
    nix_fail_stub = """#!/usr/bin/env bash
if [[ "$*" == *"builtins.currentSystem"* ]]; then
  printf 'x86_64-linux'
  exit 0
fi
echo 'error: attribute missing' >&2
exit 1
"""
    env = _isolated_env(tmp_path, path=_stubbed_path(tmp_path, nix_stub=nix_fail_stub))
    repo = _init_repo(tmp_path, env)

    result = check_nix_eval(repo, env)

    assert not result.ok


# --- run_checks / read-only 保証 ---


def test_run_checks_is_read_only(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path, with_identity=True, path=_stubbed_path(tmp_path))
    repo = _init_repo(tmp_path, env)
    _commit_initial(repo, env)
    (repo / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

    def _snapshot() -> tuple[str, bytes]:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            env=dict(env),
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return status, (repo / ".git" / "index").read_bytes()

    before = _snapshot()
    run_checks(repo, env)
    after = _snapshot()

    assert before == after


def test_run_checks_reports_all_classification_keys(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path, with_identity=True, path=_stubbed_path(tmp_path))
    repo = _init_repo(tmp_path, env)

    results = run_checks(repo, env)

    assert [r.key for r in results] == [
        KEY_CHECKOUT_KIND,
        KEY_NIX_EVAL,
        KEY_LOCK_DRIFT,
        KEY_GIT_COMMIT_IDENTITY,
        KEY_HOOK_POLICY,
    ]


# --- main / exit code ---


def test_main_exits_zero_when_all_checks_pass(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(
        preflight,
        "run_checks",
        lambda cwd, env: [CheckResult(KEY_CHECKOUT_KIND, ok=True, detail="通常 checkout")],
    )

    exit_code = preflight.main([])

    assert exit_code == 0
    assert "OK" in capsys.readouterr().out


def test_main_exits_nonzero_and_reports_classification_on_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(
        preflight,
        "run_checks",
        lambda cwd, env: [CheckResult(KEY_GIT_COMMIT_IDENTITY, ok=False, detail="identity が解決できない")],
    )

    exit_code = preflight.main([])

    assert exit_code == 1
    out = capsys.readouterr().out
    assert KEY_GIT_COMMIT_IDENTITY in out
    assert "FAIL" in out
