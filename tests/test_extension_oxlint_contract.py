"""Chrome helper extensions の共有 Oxlint 契約テスト。"""

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


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_helpers_share_oxlint_dependency_script_and_config_contract() -> None:
    expected_lint_scripts = {
        "suno-helper": "cd .. && oxlint -c .oxlintrc.json suno-helper shared",
        "distrokid-helper": "cd .. && oxlint -c .oxlintrc.json distrokid-helper",
    }

    for helper, expected_lint_script in expected_lint_scripts.items():
        helper_root = _EXTENSIONS_ROOT / helper
        package = _read_json(helper_root / "package.json")
        dev_dependencies = package["devDependencies"]
        scripts = package["scripts"]

        assert isinstance(dev_dependencies, dict)
        assert isinstance(scripts, dict)
        assert dev_dependencies["oxlint"] == "1.73.0"
        assert _ESLINT_DIRECT_DEPENDENCIES.isdisjoint(dev_dependencies)
        assert scripts["lint"] == expected_lint_script
        assert not (helper_root / "eslint.config.js").exists()

        lockfile = yaml.safe_load((helper_root / "pnpm-lock.yaml").read_text(encoding="utf-8"))
        locked_dev_dependencies = lockfile["importers"]["."]["devDependencies"]
        assert locked_dev_dependencies["oxlint"] == {"specifier": "1.73.0", "version": "1.73.0"}
        assert _ESLINT_DIRECT_DEPENDENCIES.isdisjoint(locked_dev_dependencies)

    config = _read_json(_EXTENSIONS_ROOT / ".oxlintrc.json")
    assert config["env"] == {"browser": True}
    assert config["globals"] == {"browser": "readonly", "chrome": "readonly"}
    assert config["ignorePatterns"] == [
        "**/.wxt/**",
        "**/.output/**",
        "**/dist/**",
        "**/node_modules/**",
    ]

    playlist_error_test = (_EXTENSIONS_ROOT / "suno-helper" / "tests" / "content-playlist-error.test.ts").read_text(
        encoding="utf-8"
    )
    assert "eslint-disable" not in playlist_error_test
    assert "oxlint-disable-next-line no-unused-vars" in playlist_error_test
