import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = ROOT / "extensions"
HELPERS = ("suno-helper", "distrokid-helper", "community-helper")
PRIMITIVES = (
    "alert.tsx",
    "button.tsx",
    "card.tsx",
    "checkbox.tsx",
    "field.tsx",
    "label.tsx",
    "radio-group.tsx",
    "select.tsx",
)
MIGRATED_PRIMITIVES = ("alert.tsx", "button.tsx", "card.tsx", "select.tsx")


def test_shared_ui_package_owns_public_primitives_and_theme() -> None:
    package = json.loads((EXTENSIONS / "shared-ui/package.json").read_text())

    assert package["name"] == "@youtube-automation/ui"
    assert package["exports"] == {
        ".": "./src/index.ts",
        "./theme.css": "./src/theme.css",
    }
    assert set(package["dependencies"]) == {
        "@base-ui/react",
        "class-variance-authority",
        "clsx",
        "tailwindcss",
        "tailwind-merge",
    }

    index = (EXTENSIONS / "shared-ui/src/index.ts").read_text()
    for public_symbol in (
        "Alert",
        "AlertDescription",
        "Button",
        "Card",
        "Checkbox",
        "FieldLabel",
        "RadioGroup",
        "RadioGroupItem",
        "Select",
        "cn",
    ):
        assert public_symbol in index

    for primitive in PRIMITIVES:
        assert (EXTENSIONS / f"shared-ui/src/{primitive}").is_file()


def test_shared_form_primitives_use_base_ui_state_contracts() -> None:
    checkbox = (EXTENSIONS / "shared-ui/src/checkbox.tsx").read_text()
    radio_group = (EXTENSIONS / "shared-ui/src/radio-group.tsx").read_text()

    assert 'from "@base-ui/react/checkbox"' in checkbox
    assert 'data-slot="checkbox"' in checkbox
    assert 'data-slot="checkbox-indicator"' in checkbox
    assert "data-checked" in checkbox
    assert "disabled:opacity-50" in checkbox
    assert "focus-visible:ring-[3px]" in checkbox

    assert 'from "@base-ui/react/radio"' in radio_group
    assert 'from "@base-ui/react/radio-group"' in radio_group
    assert 'data-slot="radio-group"' in radio_group
    assert 'data-slot="radio-group-item"' in radio_group
    assert 'data-slot="radio-group-indicator"' in radio_group
    assert "data-checked" in radio_group
    assert "disabled:opacity-50" in radio_group
    assert "focus-visible:ring-[3px]" in radio_group


def test_shared_theme_exposes_light_and_dark_status_token_triplets() -> None:
    theme = (EXTENSIONS / "shared-ui/src/theme.css").read_text()

    for status in ("info", "warning", "success", "destructive"):
        for role in ("background", "foreground", "border"):
            token = f"--{status}-{role}:"
            assert theme.count(token) == 2, f"{token} must exist in light and dark themes"
            assert f"--color-{status}-{role}: var(--{status}-{role});" in theme


def test_helpers_depend_on_shared_ui_without_local_primitive_copies() -> None:
    for helper_name in HELPERS:
        helper = EXTENSIONS / helper_name
        package = json.loads((helper / "package.json").read_text())

        assert package["dependencies"]["@youtube-automation/ui"] == "workspace:*"
        assert not (helper / "lib/utils.ts").exists()
        for primitive in MIGRATED_PRIMITIVES:
            assert not (helper / f"components/ui/{primitive}").exists()


def test_select_consumers_dedupe_base_ui_and_react_from_their_workspace() -> None:
    for helper_name in ("suno-helper", "distrokid-helper"):
        helper = EXTENSIONS / helper_name
        package = json.loads((helper / "package.json").read_text())
        assert package["dependencies"]["@base-ui/react"] == "1.6.0"
        for config_name in ("vitest.config.ts", "wxt.config.ts"):
            config = (helper / config_name).read_text()
            assert '"react", "react-dom", "@base-ui/react"' in config

    fallow = json.loads((EXTENSIONS / ".fallowrc.json").read_text())
    assert fallow["ignoreDependencies"] == []


def test_all_shadcn_configs_choose_base_vega() -> None:
    for workspace in ("shared-ui", *HELPERS):
        config = json.loads((EXTENSIONS / workspace / "components.json").read_text())
        assert config["style"] == "base-vega"


def test_helpers_import_the_shared_theme_contract() -> None:
    styles = (
        EXTENSIONS / "suno-helper/components/overlay.css",
        EXTENSIONS / "suno-helper/entrypoints/popup/style.css",
        EXTENSIONS / "distrokid-helper/entrypoints/popup/style.css",
        EXTENSIONS / "community-helper/entrypoints/popup/style.css",
    )

    for style in styles:
        assert '@import "@youtube-automation/ui/theme.css";' in style.read_text()


def test_shared_ui_is_in_the_extension_lint_gate() -> None:
    shared_package = json.loads((EXTENSIONS / "shared-ui/package.json").read_text())
    suno_package = json.loads((EXTENSIONS / "suno-helper/package.json").read_text())

    assert shared_package["scripts"]["check"] == ("pnpm --dir .. exec ultracite check shared-ui")
    assert "shared-ui" in suno_package["scripts"]["check"]
