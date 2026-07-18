"""Chrome helper extensions の共有 Oxlint + Oxfmt（ultracite）契約テスト。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import yaml

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
_EXTENSIONS_ROOT: Final[Path] = _REPO_ROOT / "extensions"
_ESLINT_DIRECT_DEPENDENCIES: Final[set[str]] = {
    "@eslint/js",
    "eslint",
    "eslint-plugin-react-hooks",
    "typescript-eslint",
}
_REPLACED_FORMATTER_DEPENDENCIES: Final[set[str]] = {"prettier"}
_TOOLCHAIN_VERSIONS: Final[dict[str, str]] = {
    "oxlint": "1.73.0",
    "oxfmt": "0.59.0",
    "ultracite": "7.9.4",
}


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_helpers_share_ultracite_dependency_script_and_config_contract() -> None:
    expected_check_scripts = {
        "suno-helper": "cd .. && ultracite check suno-helper shared",
        "distrokid-helper": "cd .. && ultracite check distrokid-helper",
    }
    expected_fix_scripts = {
        "suno-helper": "cd .. && ultracite fix suno-helper shared",
        "distrokid-helper": "cd .. && ultracite fix distrokid-helper",
    }

    for helper, expected_check_script in expected_check_scripts.items():
        helper_root = _EXTENSIONS_ROOT / helper
        package = _read_json(helper_root / "package.json")
        dev_dependencies = package["devDependencies"]
        scripts = package["scripts"]

        assert isinstance(dev_dependencies, dict)
        assert isinstance(scripts, dict)
        for tool, version in _TOOLCHAIN_VERSIONS.items():
            assert dev_dependencies[tool] == version
        assert _ESLINT_DIRECT_DEPENDENCIES.isdisjoint(dev_dependencies)
        assert _REPLACED_FORMATTER_DEPENDENCIES.isdisjoint(dev_dependencies)
        assert scripts["check"] == expected_check_script
        assert scripts["fix"] == expected_fix_scripts[helper]
        assert "lint" not in scripts
        assert "format" not in scripts
        assert "format:check" not in scripts
        assert not (helper_root / "eslint.config.js").exists()

        lockfile = yaml.safe_load((helper_root / "pnpm-lock.yaml").read_text(encoding="utf-8"))
        locked_dev_dependencies = lockfile["importers"]["."]["devDependencies"]
        for tool, version in _TOOLCHAIN_VERSIONS.items():
            assert locked_dev_dependencies[tool]["specifier"] == version
        assert _ESLINT_DIRECT_DEPENDENCIES.isdisjoint(locked_dev_dependencies)
        assert _REPLACED_FORMATTER_DEPENDENCIES.isdisjoint(locked_dev_dependencies)

    assert not (_EXTENSIONS_ROOT / ".oxlintrc.json").exists()

    # 共有 config（oxlint.config.ts / oxfmt.config.ts）の ultracite import は
    # extensions/node_modules で解決する（helper の node_modules へは届かないため必須）。
    toolchain_package = _read_json(_EXTENSIONS_ROOT / "package.json")
    toolchain_dev_dependencies = toolchain_package["devDependencies"]
    assert isinstance(toolchain_dev_dependencies, dict)
    assert toolchain_dev_dependencies == _TOOLCHAIN_VERSIONS
    toolchain_lockfile = yaml.safe_load((_EXTENSIONS_ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8"))
    toolchain_locked = toolchain_lockfile["importers"]["."]["devDependencies"]
    for tool, version in _TOOLCHAIN_VERSIONS.items():
        assert toolchain_locked[tool]["specifier"] == version

    oxlint_config = (_EXTENSIONS_ROOT / "oxlint.config.ts").read_text(encoding="utf-8")
    assert 'import core from "ultracite/oxlint/core";' in oxlint_config
    assert 'import react from "ultracite/oxlint/react";' in oxlint_config
    assert "extends: [core, react]" in oxlint_config
    # 旧 .oxlintrc.json のルール水準を維持する（globals / react-hooks 契約）。
    assert '"react/rules-of-hooks": "error"' in oxlint_config
    assert '"react/exhaustive-deps": "warn"' in oxlint_config
    assert '"react/react-compiler": "off"' in oxlint_config
    assert 'browser: "readonly"' in oxlint_config
    assert 'chrome: "readonly"' in oxlint_config
    assert '"**/.wxt/**"' in oxlint_config

    oxfmt_config = (_EXTENSIONS_ROOT / "oxfmt.config.ts").read_text(encoding="utf-8")
    assert 'import ultracite from "ultracite/oxfmt";' in oxfmt_config
    assert "...ultracite," in oxfmt_config

    playlist_error_test = (_EXTENSIONS_ROOT / "suno-helper" / "tests" / "content-playlist-error.test.ts").read_text(
        encoding="utf-8"
    )
    assert "eslint-disable" not in playlist_error_test
    assert "oxlint-disable-next-line no-unused-vars" in playlist_error_test
