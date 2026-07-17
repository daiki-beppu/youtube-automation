"""yt-preflight: worktree / clone 環境を実装着手前に read-only 検査・分類する CLI（#2124）。

takt 一括実行で発生した「環境不備が実装後・publication 段階まで検出されない」構造
（Git identity 欠落による auto-commit 失敗、Nix eval 失敗、lock drift、lefthook 未導入）
を、実装前の 1 コマンドで分類・報告する。すべての検査は read-only で、
リポジトリの working tree / index を変更しない。

Usage:
    uv run yt-preflight

Exit codes:
    0: 全検査項目が合格
    1: 1 件以上の検査項目が不合格
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# 分類キー（報告・機械照合用）
KEY_CHECKOUT_KIND = "checkout_kind"
KEY_NIX_EVAL = "nix_eval"
KEY_LOCK_DRIFT = "lock_drift"
KEY_GIT_COMMIT_IDENTITY = "git_commit_identity"
KEY_HOOK_POLICY = "hook_policy"

SKIP_LEFTHOOK_ENV = "YOUTUBE_AUTOMATION_SKIP_LEFTHOOK"

# default 実行 60 秒未満の要件を守るための per-check タイムアウト
_GIT_TIMEOUT_SECONDS = 10
_UV_TIMEOUT_SECONDS = 30
_NIX_TIMEOUT_SECONDS = 45

_HOOK_NAMES = ("pre-commit", "pre-push")


@dataclass(frozen=True)
class CheckResult:
    """1 検査項目の結果。detail に identity 等の秘匿値を含めてはならない。"""

    key: str
    ok: bool
    detail: str


def _run_command(
    args: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: int,
) -> subprocess.CompletedProcess[str] | None:
    """外部コマンドを read-only 前提で実行する。タイムアウト時は None を返す。"""
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            env=dict(env),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None


def _git_path(name: str, *, cwd: Path, env: Mapping[str, str]) -> Path | None:
    proc = _run_command(
        ["git", "rev-parse", "--path-format=absolute", "--git-path", name],
        cwd=cwd,
        env=env,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    if proc is None or proc.returncode != 0:
        return None
    return Path(proc.stdout.strip())


def check_checkout_kind(cwd: Path, env: Mapping[str, str]) -> CheckResult:
    """checkout 種別（通常 checkout / linked worktree / takt 管理 clone）を分類する。"""
    proc = _run_command(
        ["git", "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"],
        cwd=cwd,
        env=env,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    if proc is None or proc.returncode != 0:
        return CheckResult(KEY_CHECKOUT_KIND, ok=False, detail="Git checkout ではない（git rev-parse が失敗）")

    lines = proc.stdout.splitlines()
    if len(lines) < 2:
        return CheckResult(KEY_CHECKOUT_KIND, ok=False, detail="git rev-parse の出力を解釈できない")
    git_dir, common_dir = (Path(line.strip()) for line in lines[:2])

    # takt runtime は XDG_CONFIG_HOME を <clone>/.takt/.runtime/config へ向ける
    xdg_config_home = env.get("XDG_CONFIG_HOME", "")
    is_takt_clone = (
        bool(env.get("TAKT_RUNTIME_ROOT"))
        or f"{os.sep}.takt{os.sep}" in xdg_config_home
        or (cwd / ".takt" / ".runtime").is_dir()
    )
    if is_takt_clone:
        kind = "takt 管理 clone"
    elif git_dir != common_dir:
        kind = "linked worktree"
    else:
        kind = "通常 checkout"
    return CheckResult(KEY_CHECKOUT_KIND, ok=True, detail=kind)


def check_git_commit_identity(cwd: Path, env: Mapping[str, str]) -> CheckResult:
    """commit に必要な Git identity が解決できるか検査する。

    identity の値そのもの（名前・メールアドレス）は detail に含めない。
    """
    failed_vars = []
    for var in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        proc = _run_command(
            ["git", "var", var],
            cwd=cwd,
            env=env,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        if proc is None or proc.returncode != 0:
            failed_vars.append(var)
    if failed_vars:
        return CheckResult(
            KEY_GIT_COMMIT_IDENTITY,
            ok=False,
            detail=(
                f"{' / '.join(failed_vars)} が解決できない。"
                "user.name / user.email が現在の XDG_CONFIG_HOME 配下から見えているか確認する"
            ),
        )
    return CheckResult(KEY_GIT_COMMIT_IDENTITY, ok=True, detail="author / committer identity を解決できる")


def check_hook_policy(cwd: Path, env: Mapping[str, str]) -> CheckResult:
    """lefthook が導入済みか、または明示 skip されているかを検査する。

    曖昧な「未導入」（env 未設定かつ hook 未配置）は不合格にする。
    """
    if env.get(SKIP_LEFTHOOK_ENV) == "1":
        return CheckResult(KEY_HOOK_POLICY, ok=True, detail=f"{SKIP_LEFTHOOK_ENV}=1 による明示 skip")

    missing = []
    for hook_name in _HOOK_NAMES:
        hook_path = _git_path(f"hooks/{hook_name}", cwd=cwd, env=env)
        if hook_path is None or not hook_path.is_file():
            missing.append(hook_name)
            continue
        try:
            content = hook_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            missing.append(hook_name)
            continue
        if "lefthook" not in content:
            missing.append(hook_name)
    if missing:
        return CheckResult(
            KEY_HOOK_POLICY,
            ok=False,
            detail=(
                f"lefthook hook が未導入（{', '.join(missing)}）。"
                f"'bash .lefthook/setup-worktree.sh' を実行するか、意図的な skip なら {SKIP_LEFTHOOK_ENV}=1 を設定する"
            ),
        )
    return CheckResult(KEY_HOOK_POLICY, ok=True, detail="lefthook hook が導入済み")


def check_lock_drift(cwd: Path, env: Mapping[str, str]) -> CheckResult:
    """uv.lock が pyproject.toml と同期しているか検査する（uv lock --check は read-only）。"""
    if shutil.which("uv", path=env.get("PATH")) is None:
        return CheckResult(KEY_LOCK_DRIFT, ok=False, detail="uv が PATH にない")
    proc = _run_command(
        ["uv", "lock", "--check"],
        cwd=cwd,
        env=env,
        timeout=_UV_TIMEOUT_SECONDS,
    )
    if proc is None:
        return CheckResult(
            KEY_LOCK_DRIFT, ok=False, detail=f"uv lock --check が {_UV_TIMEOUT_SECONDS}s 以内に完了しない"
        )
    if proc.returncode != 0:
        return CheckResult(
            KEY_LOCK_DRIFT,
            ok=False,
            detail="uv.lock が pyproject.toml とずれている（devShell の dependency sync が失敗している可能性）",
        )
    return CheckResult(KEY_LOCK_DRIFT, ok=True, detail="uv.lock は pyproject.toml と同期している")


def check_nix_eval(cwd: Path, env: Mapping[str, str]) -> CheckResult:
    """flake の devShell が評価可能か検査する（eval のみ、build はしない）。"""
    if shutil.which("nix", path=env.get("PATH")) is None:
        return CheckResult(KEY_NIX_EVAL, ok=False, detail="nix が PATH にない")

    system_proc = _run_command(
        ["nix", "eval", "--impure", "--raw", "--expr", "builtins.currentSystem"],
        cwd=cwd,
        env=env,
        timeout=_NIX_TIMEOUT_SECONDS,
    )
    if system_proc is None or system_proc.returncode != 0:
        return CheckResult(KEY_NIX_EVAL, ok=False, detail="builtins.currentSystem を評価できない")
    system = system_proc.stdout.strip()

    # --no-write-lock-file: 検査が flake.lock を書き換えないことを保証する（read-only 要件）
    eval_proc = _run_command(
        ["nix", "eval", "--no-write-lock-file", "--raw", f".#devShells.{system}.default.drvPath"],
        cwd=cwd,
        env=env,
        timeout=_NIX_TIMEOUT_SECONDS,
    )
    if eval_proc is None:
        return CheckResult(KEY_NIX_EVAL, ok=False, detail=f"flake eval が {_NIX_TIMEOUT_SECONDS}s 以内に完了しない")
    if eval_proc.returncode != 0:
        return CheckResult(
            KEY_NIX_EVAL,
            ok=False,
            detail=f"devShells.{system}.default を評価できない（flake.nix / flake.lock を確認する）",
        )
    return CheckResult(KEY_NIX_EVAL, ok=True, detail=f"devShells.{system}.default を評価できる")


def run_checks(cwd: Path, env: Mapping[str, str]) -> list[CheckResult]:
    """全検査項目を実行する。すべて read-only。"""
    return [
        check_checkout_kind(cwd, env),
        check_nix_eval(cwd, env),
        check_lock_drift(cwd, env),
        check_git_commit_identity(cwd, env),
        check_hook_policy(cwd, env),
    ]


def format_report(results: list[CheckResult]) -> str:
    lines = ["=== yt-preflight ==="]
    for result in results:
        status = "OK  " if result.ok else "FAIL"
        lines.append(f"[{status}] {result.key}: {result.detail}")
    failed = [r for r in results if not r.ok]
    if failed:
        lines.append(f"NG: {len(failed)}/{len(results)} 項目が不合格（{', '.join(r.key for r in failed)}）")
    else:
        lines.append(f"OK: 全 {len(results)} 項目が合格")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yt-preflight",
        description="worktree / clone 環境を実装着手前に read-only 検査・分類する",
    )
    parser.parse_args(argv)

    results = run_checks(Path.cwd(), os.environ)
    print(format_report(results))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
