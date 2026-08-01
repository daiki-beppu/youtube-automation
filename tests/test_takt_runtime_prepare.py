"""`.takt/runtime-prepare.sh` が worker 環境へ注入する runtime path 契約（#3040）。

このスクリプトの stdout（KEY=VALUE 行）が takt worker の環境になる。
`yt-preflight` の `check_runtime_path` は同じ変数群が current runtime root 配下に
あることを検査するため、両者の変数集合がずれると「注入されていない変数を誰も
検査しない」死角が生まれる。#3040 はまさにその死角（NIX_CACHE_HOME）だった。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from youtube_automation.commands.system.preflight import RUNTIME_PATH_ENV_VARS

ROOT = Path(__file__).resolve().parents[1]
PREPARE_SCRIPT = ROOT / ".takt" / "runtime-prepare.sh"


def _run_prepare(tmp_path: Path, *, inherited: dict[str, str] | None = None) -> dict[str, str]:
    """runtime root を tmp へ向けてスクリプトを実行し、注入される環境を返す。

    cwd は `pyproject.toml` を持たない tmp にする。スクリプトは pyproject.toml が
    ある場合だけ `uv sync` を実行するため、これで事前同期を回避できる。
    """
    runtime_root = tmp_path / "current" / ".takt" / ".runtime"
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "TAKT_RUNTIME_ROOT": str(runtime_root),
        **(inherited or {}),
    }

    result = subprocess.run(
        ["bash", str(PREPARE_SCRIPT)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    injected = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        assert separator, f"KEY=VALUE 契約に反する出力: {line!r}"
        injected[key] = value
    return injected


def test_injected_variables_match_the_preflight_contract(tmp_path: Path) -> None:
    """スクリプトの注入対象と preflight の検査対象が完全に一致する."""
    injected = _run_prepare(tmp_path)

    assert set(injected) == set(RUNTIME_PATH_ENV_VARS)


def test_every_injected_path_is_under_the_current_runtime_root(tmp_path: Path) -> None:
    injected = _run_prepare(tmp_path)
    runtime_root = tmp_path / "current" / ".takt" / ".runtime"

    for var, value in injected.items():
        path = Path(value)
        assert path.is_absolute(), var
        assert path.is_relative_to(runtime_root), var
        assert path.is_dir(), f"{var} のディレクトリが作成されていない"


@pytest.mark.parametrize("var", RUNTIME_PATH_ENV_VARS)
def test_sibling_worktree_values_are_overwritten(tmp_path: Path, var: str) -> None:
    """継承した sibling worktree の値を残さない（#2163 / #3040）."""
    sibling = tmp_path / "sibling-worktree" / ".takt" / ".runtime" / "leaked"
    sibling.mkdir(parents=True)

    injected = _run_prepare(tmp_path, inherited={var: str(sibling)})

    assert injected[var] != str(sibling)
    assert "sibling-worktree" not in injected[var]


def test_nix_cache_home_matches_the_dev_shell_derivation(tmp_path: Path) -> None:
    """#3040: devShell 入場時に shellHook が導出する値と一致させる.

    `.nix/worktree-tmpdir.sh` は TMPDIR が checkout 内を指すとき現値をそのまま
    返すため、worker では `flake.nix` shellHook / `.envrc` が `$TMPDIR/nix-cache`
    を export する。ここで別の値を注入すると `nix develop` の前後で cache path が
    動き、評価結果が毎回捨てられる。
    """
    injected = _run_prepare(tmp_path)

    assert injected["NIX_CACHE_HOME"] == f"{injected['TMPDIR']}/nix-cache"


def test_dev_shell_derives_nix_cache_home_from_tmpdir() -> None:
    """上のテストが前提にしている shellHook 側の導出規則を固定する."""
    shell_hook = (ROOT / "flake.nix").read_text(encoding="utf-8")
    envrc = (ROOT / ".envrc").read_text(encoding="utf-8")

    assert 'export NIX_CACHE_HOME="$worktree_tmpdir/nix-cache"' in shell_hook
    assert 'export NIX_CACHE_HOME="$worktree_tmpdir/nix-cache"' in envrc
