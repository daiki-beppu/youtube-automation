"""Chrome helper extensions の共有 Oxlint + Oxfmt（ultracite）契約テスト。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import pytest
import yaml

from tests.helpers.paths import REPO_ROOT

_REPO_ROOT: Final[Path] = REPO_ROOT
_EXTENSIONS_ROOT: Final[Path] = _REPO_ROOT / "extensions"
_HELPERS: Final[tuple[str, ...]] = ("suno-helper", "distrokid-helper")
_ESLINT_DIRECT_DEPENDENCIES: Final[set[str]] = {
    "@eslint/js",
    "eslint",
    "eslint-plugin-react-hooks",
    "typescript-eslint",
}
_REPLACED_FORMATTER_DEPENDENCIES: Final[set[str]] = {"prettier"}
_TOOLCHAIN_VERSIONS: Final[dict[str, str]] = {
    "oxlint": "1.74.0",
    "oxfmt": "0.59.0",
    "ultracite": "7.9.4",
}
_CHECK_SCRIPTS: Final[dict[str, str]] = {
    "suno-helper": "cd .. && ultracite check suno-helper shared shared-ui",
    "distrokid-helper": "cd .. && ultracite check distrokid-helper",
}
_FIX_SCRIPTS: Final[dict[str, str]] = {
    "suno-helper": "cd .. && ultracite fix suno-helper shared shared-ui",
    "distrokid-helper": "cd .. && ultracite fix distrokid-helper",
}


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("helper", _HELPERS)
def test_helper_package_uses_only_the_shared_ultracite_entrypoints(helper: str) -> None:
    helper_root = _EXTENSIONS_ROOT / helper
    package = _read_json(helper_root / "package.json")
    dev_dependencies = package["devDependencies"]
    scripts = package["scripts"]

    assert isinstance(dev_dependencies, dict)
    assert isinstance(scripts, dict)
    assert {tool: dev_dependencies[tool] for tool in _TOOLCHAIN_VERSIONS} == _TOOLCHAIN_VERSIONS
    assert _ESLINT_DIRECT_DEPENDENCIES.isdisjoint(dev_dependencies)
    assert _REPLACED_FORMATTER_DEPENDENCIES.isdisjoint(dev_dependencies)
    assert scripts["check"] == _CHECK_SCRIPTS[helper]
    assert scripts["fix"] == _FIX_SCRIPTS[helper]
    assert {"lint", "format", "format:check"}.isdisjoint(scripts)
    assert not (helper_root / "eslint.config.js").exists()


@pytest.mark.parametrize("helper", _HELPERS)
def test_helper_lockfile_pins_the_shared_ultracite_toolchain(helper: str) -> None:
    lockfile = yaml.safe_load((_EXTENSIONS_ROOT / helper / "pnpm-lock.yaml").read_text(encoding="utf-8"))
    locked = lockfile["importers"]["."]["devDependencies"]

    assert {tool: locked[tool]["specifier"] for tool in _TOOLCHAIN_VERSIONS} == _TOOLCHAIN_VERSIONS
    assert _ESLINT_DIRECT_DEPENDENCIES.isdisjoint(locked)
    assert _REPLACED_FORMATTER_DEPENDENCIES.isdisjoint(locked)


def test_extensions_root_owns_the_config_resolution_toolchain() -> None:
    package = _read_json(_EXTENSIONS_ROOT / "package.json")
    dependencies = package["devDependencies"]
    lockfile = yaml.safe_load((_EXTENSIONS_ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8"))
    locked = lockfile["importers"]["."]["devDependencies"]

    assert dependencies == _TOOLCHAIN_VERSIONS
    assert {tool: locked[tool]["specifier"] for tool in _TOOLCHAIN_VERSIONS} == _TOOLCHAIN_VERSIONS


def test_oxlint_config_preserves_shared_react_and_browser_rules() -> None:
    config = (_EXTENSIONS_ROOT / "oxlint.config.ts").read_text(encoding="utf-8")

    assert 'import core from "ultracite/oxlint/core";' in config
    assert 'import react from "ultracite/oxlint/react";' in config
    assert "extends: [core, react]" in config
    assert '"react/rules-of-hooks": "error"' in config
    assert '"react/exhaustive-deps": "warn"' in config
    assert '"react/react-compiler": "off"' in config
    assert 'browser: "readonly"' in config
    assert 'chrome: "readonly"' in config
    assert '"**/.wxt/**"' in config
    assert not (_EXTENSIONS_ROOT / ".oxlintrc.json").exists()


def test_oxfmt_config_extends_ultracite() -> None:
    config = (_EXTENSIONS_ROOT / "oxfmt.config.ts").read_text(encoding="utf-8")

    assert 'import ultracite from "ultracite/oxfmt";' in config
    assert "...ultracite," in config


def test_playlist_error_fixture_uses_the_oxlint_suppression() -> None:
    source = (_EXTENSIONS_ROOT / "suno-helper" / "tests" / "content-playlist-error.test.ts").read_text(encoding="utf-8")

    assert "eslint-disable" not in source
    assert "oxlint-disable-next-line no-unused-vars" in source
