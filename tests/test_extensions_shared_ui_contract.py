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
    "collapsible.tsx",
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
        "Collapsible",
        "CollapsibleContent",
        "CollapsibleTrigger",
        "FieldError",
        "FieldLabel",
        "FieldSet",
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
    assert "focus-visible:ring-3" in checkbox
    assert "data-indeterminate:bg-primary" in checkbox
    assert "aria-invalid:ring-3" in checkbox

    assert 'from "@base-ui/react/radio"' in radio_group
    assert 'from "@base-ui/react/radio-group"' in radio_group
    assert 'data-slot="radio-group"' in radio_group
    assert 'data-slot="radio-group-item"' in radio_group
    assert 'data-slot="radio-group-indicator"' in radio_group
    assert "data-checked" in radio_group
    assert "disabled:opacity-50" in radio_group
    assert "focus-visible:ring-3" in radio_group
    assert "aria-invalid:ring-3" in radio_group
    assert "data-checked:bg-primary" not in radio_group
    assert 'className="flex size-4 items-center justify-center"' in radio_group
    assert "left-1/2 top-1/2" in radio_group
    assert "-translate-x-1/2 -translate-y-1/2" in radio_group
    assert "rounded-full bg-current" in radio_group


def test_shared_collapsible_tracks_current_base_vega_composition() -> None:
    collapsible = (EXTENSIONS / "shared-ui/src/collapsible.tsx").read_text()

    assert 'from "@base-ui/react/collapsible"' in collapsible
    assert 'data-slot="collapsible"' in collapsible
    assert 'data-slot="collapsible-trigger"' in collapsible
    assert 'data-slot="collapsible-content"' in collapsible
    assert "CollapsiblePrimitive.Root.Props" in collapsible
    assert "CollapsiblePrimitive.Trigger.Props" in collapsible
    assert "CollapsiblePrimitive.Panel.Props" in collapsible


def test_shared_primitives_track_current_base_vega_composition() -> None:
    sources = {
        name: (EXTENSIONS / f"shared-ui/src/{name}.tsx").read_text()
        for name in ("alert", "button", "card", "field", "select")
    }

    assert "[&_p:not(:last-child)]:mb-4" in sources["alert"]
    assert "group/button" in sources["button"]
    assert '"icon-xs"' in sources["button"]
    assert "active:not-aria-[haspopup]:translate-y-px" in sources["button"]
    assert "has-[>img:first-child]:pt-0" in sources["card"]
    assert "has-data-[slot=card-action]:grid-cols-[1fr_auto]" in sources["card"]

    for slot in (
        "field-set",
        "field-legend",
        "field-group",
        "field-title",
        "field-separator",
        "field-error",
    ):
        assert f'data-slot="{slot}"' in sources["field"]

    assert "*:data-[slot=select-value]:line-clamp-1" in sources["select"]
    assert "data-[side=bottom]:slide-in-from-top-2" in sources["select"]
    assert "SelectPortalContext" in sources["select"]


def test_shared_theme_is_light_only() -> None:
    theme = (EXTENSIONS / "shared-ui/src/theme.css").read_text()

    assert "--background: oklch(0.97 0 0);" in theme
    assert "--card: oklch(1 0 0);" in theme
    assert "--popover: oklch(1 0 0);" in theme
    assert "@custom-variant dark" not in theme
    assert ".dark" not in theme
    assert ":host(.dark)" not in theme

    for status in ("info", "warning", "success", "destructive"):
        for role in ("background", "foreground", "border"):
            token = f"--{status}-{role}:"
            assert theme.count(token) == 1, f"{token} must exist once in the light theme"
            assert f"--color-{status}-{role}: var(--{status}-{role});" in theme

    source_roots = [EXTENSIONS / "shared-ui/src"]
    source_roots.extend(
        EXTENSIONS / helper / directory for helper in HELPERS for directory in ("components", "entrypoints", "lib")
    )
    sources = "\n".join(
        path.read_text()
        for source_root in source_roots
        if source_root.exists()
        for path in source_root.rglob("*")
        if path.suffix in {".css", ".ts", ".tsx"}
    )
    assert "dark:" not in sources
    assert "prefers-color-scheme" not in sources
    assert not (EXTENSIONS / "shared-ui/src/color-scheme.ts").exists()
    assert "watchColorScheme" not in sources


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
    assert fallow["ignoreDependencies"] == ["@base-ui/react"]


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
