"""Chrome 拡張の TypeScript 版数固定と lockfile 整合の契約を検証する。"""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXTENSION_NAMES = ("suno-helper", "distrokid-helper")
_PINNED_TYPESCRIPT = "7.0.2"


def _read(path: str) -> str:
    return (_REPO_ROOT / path).read_text(encoding="utf-8")


def test_both_extensions_pin_typescript_seven() -> None:
    for name in _EXTENSION_NAMES:
        package = json.loads(_read(f"extensions/{name}/package.json"))

        assert package["devDependencies"]["typescript"] == _PINNED_TYPESCRIPT, name


def test_both_lockfiles_resolve_the_pinned_typescript() -> None:
    for name in _EXTENSION_NAMES:
        lockfile = _read(f"extensions/{name}/pnpm-lock.yaml")

        assert f"typescript@{_PINNED_TYPESCRIPT}" in lockfile, name
        assert "typescript@5." not in lockfile, name


def test_both_tsconfigs_avoid_options_removed_in_typescript_seven() -> None:
    for name in _EXTENSION_NAMES:
        tsconfig = _read(f"extensions/{name}/tsconfig.json")

        assert "baseUrl" not in tsconfig, name
