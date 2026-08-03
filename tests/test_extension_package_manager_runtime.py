"""Nix extensions shell と pnpm wrapper の Worker 環境契約を検証する。"""

from __future__ import annotations

import os
import subprocess

import pytest

from tests.helpers.paths import REPO_ROOT

_NIX_TIMEOUT_SECONDS = 180


def _run_extensions(command: str, *, worker_value: str | None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if worker_value is None:
        env.pop("PNPM_MAX_WORKERS", None)
    else:
        env["PNPM_MAX_WORKERS"] = worker_value
    try:
        return subprocess.run(
            [
                "nix",
                "develop",
                f"{REPO_ROOT}#extensions",
                "--command",
                "sh",
                "-c",
                command,
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=_NIX_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        pytest.skip("nix executable is unavailable")


def _assert_success(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def _trailing_lines(result: subprocess.CompletedProcess[str], count: int) -> list[str]:
    """stdout の末尾 count 行を返す。

    `node_modules` が無い環境では `pnpm exec` が依存インストールを先に走らせ、その進捗
    出力が stdout の先頭へ混ざる（CI のクリーンチェックアウトが該当）。検証対象は
    Worker 値だけなので末尾から取り、テストの実行順やインストール済みかどうかに
    依存しないようにする。
    """
    return result.stdout.strip().splitlines()[-count:]


def test_extensions_shell_initializes_an_unset_worker_limit() -> None:
    """REQ-3078-01 / TC-01C: an unset parent value becomes one in the shell."""
    result = _run_extensions('printf "%s" "$PNPM_MAX_WORKERS"', worker_value=None)

    _assert_success(result)
    assert result.stdout == "1"


def test_extensions_shell_treats_an_empty_worker_limit_as_unset() -> None:
    """REQ-3078-01 / TC-01D: an empty parent value becomes one in the shell."""
    result = _run_extensions('printf "%s" "$PNPM_MAX_WORKERS"', worker_value="")

    _assert_success(result)
    assert result.stdout == "1"


def test_pnpm_wrapper_initializes_a_worker_limit_after_shell_unset() -> None:
    """REQ-3078-01 / TC-01E: pnpm supplies one at its process boundary."""
    command = "unset PNPM_MAX_WORKERS; pnpm -C extensions/suno-helper exec node -p 'process.env.PNPM_MAX_WORKERS'"
    result = _run_extensions(command, worker_value=None)

    _assert_success(result)
    assert _trailing_lines(result, 1) == ["1"]


def test_worker_override_reaches_the_pnpm_child_node_process() -> None:
    """REQ-3078-01 / TC-01F: an explicit seven survives both boundaries."""
    command = (
        "printf '%s\\n' \"$PNPM_MAX_WORKERS\"; "
        "pnpm -C extensions/suno-helper exec node -p "
        "'process.env.PNPM_MAX_WORKERS'"
    )
    result = _run_extensions(command, worker_value="7")

    _assert_success(result)
    assert _trailing_lines(result, 2) == ["7", "7"]
