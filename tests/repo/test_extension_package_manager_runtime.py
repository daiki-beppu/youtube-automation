"""Nix extensions shell と pnpm wrapper の Worker 環境契約を検証する。"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT

_NIX_TIMEOUT_SECONDS = 180

# pnpm の子プロセスが受け取った Worker 値をラベル付きで出力する。pnpm 自身が
# `Already up to date` / `Done in ...` を stdout へ混ぜ、その位置は検証値の前後どちらにも
# なりうるため、行の位置ではなく行の集合として検査できるようラベルを付ける。
_CHILD_PROBE = """node -p '"CHILD=" + process.env.PNPM_MAX_WORKERS'"""


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


def _dependency_free_project(tmp_path: Path) -> str:
    """依存を持たない pnpm project を作り、shell へ渡せる形のパスを返す。

    検証している契約は `PNPM_MAX_WORKERS` が pnpm のプロセス境界を越えることだけで、どの
    project 上で実行するかは含まれない。`extensions/suno-helper` を対象にすると `pnpm exec` が
    依存ツリー（494 パッケージ）の実インストールを先に走らせ、その失敗がそのままテストの失敗に
    なる。依存ゼロなら外部ダウンロードが発生せず、`node_modules` の有無にも左右されない。
    """
    project = tmp_path / "pnpm-worker-probe"
    project.mkdir()
    manifest = {"name": "pnpm-worker-probe", "version": "0.0.0", "private": True}
    (project / "package.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    return shlex.quote(str(project))


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


def test_pnpm_wrapper_initializes_a_worker_limit_after_shell_unset(tmp_path: Path) -> None:
    """REQ-3078-01 / TC-01E: pnpm supplies one at its process boundary."""
    project = _dependency_free_project(tmp_path)
    command = f"unset PNPM_MAX_WORKERS; pnpm -C {project} exec {_CHILD_PROBE}"
    result = _run_extensions(command, worker_value=None)

    _assert_success(result)
    assert "CHILD=1" in result.stdout.splitlines()


def test_worker_override_reaches_the_pnpm_child_node_process(tmp_path: Path) -> None:
    """REQ-3078-01 / TC-01F: an explicit seven survives both boundaries."""
    project = _dependency_free_project(tmp_path)
    command = f"printf 'SHELL=%s\\n' \"$PNPM_MAX_WORKERS\"; pnpm -C {project} exec {_CHILD_PROBE}"
    result = _run_extensions(command, worker_value="7")

    _assert_success(result)
    lines = result.stdout.splitlines()
    assert "SHELL=7" in lines
    assert "CHILD=7" in lines
