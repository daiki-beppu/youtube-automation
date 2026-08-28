"""Shared UI の配布設定に限定した repository contract tests."""

from __future__ import annotations

import json

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
EXTENSIONS = ROOT / "extensions"
HELPERS = ("suno-helper", "distrokid-helper", "community-helper")


def test_shared_ui_consumers_dedupe_base_ui_and_react_from_their_workspace() -> None:
    for helper_name in HELPERS:
        helper = EXTENSIONS / helper_name
        package = json.loads((helper / "package.json").read_text(encoding="utf-8"))
        assert package["dependencies"]["@base-ui/react"] == "1.6.0"
        for config_name in ("vitest.config.ts", "wxt.config.ts"):
            config = (helper / config_name).read_text(encoding="utf-8")
            assert '"react", "react-dom", "@base-ui/react"' in config

    fallow = json.loads((EXTENSIONS / ".fallowrc.json").read_text(encoding="utf-8"))
    assert fallow["ignoreDependencies"] == ["@base-ui/react"]


def test_all_shadcn_configs_choose_base_vega() -> None:
    for workspace in ("shared-ui", *HELPERS):
        config = json.loads((EXTENSIONS / workspace / "components.json").read_text(encoding="utf-8"))
        assert config["style"] == "base-vega"


def test_helpers_import_the_shared_theme_contract() -> None:
    styles = (
        EXTENSIONS / "suno-helper/components/overlay.css",
        EXTENSIONS / "distrokid-helper/components/overlay.css",
        EXTENSIONS / "community-helper/components/overlay.css",
    )

    for style in styles:
        assert '@import "@youtube-automation/ui/theme.css";' in style.read_text(encoding="utf-8")


def test_shared_ui_is_in_the_extension_lint_gate() -> None:
    shared_package = json.loads((EXTENSIONS / "shared-ui/package.json").read_text(encoding="utf-8"))
    suno_package = json.loads((EXTENSIONS / "suno-helper/package.json").read_text(encoding="utf-8"))

    assert shared_package["scripts"]["check"] == "pnpm --dir .. exec ultracite check shared-ui"
    assert "shared-ui" in suno_package["scripts"]["check"]
