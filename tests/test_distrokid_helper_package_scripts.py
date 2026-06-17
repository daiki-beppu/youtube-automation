from __future__ import annotations

import json
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE_JSON = _REPO_ROOT / "extensions" / "distrokid-helper" / "package.json"


def _load_distrokid_helper_package() -> dict[str, object]:
    return json.loads(_PACKAGE_JSON.read_text(encoding="utf-8"))


def _scripts() -> dict[str, str]:
    package = _load_distrokid_helper_package()
    scripts = package["scripts"]
    assert isinstance(scripts, dict)
    return scripts


def test_should_lint_shared_package_when_distrokid_helper_lint_runs() -> None:
    scripts = _scripts()

    assert (
        scripts["lint"]
        == "cd .. && eslint -c distrokid-helper/eslint.config.js distrokid-helper shared"
    )


def test_should_check_shared_formatting_when_distrokid_helper_format_check_runs() -> None:
    scripts = _scripts()

    assert scripts["format:check"] == "prettier --check . ../shared"
