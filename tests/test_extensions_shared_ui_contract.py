import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = ROOT / "extensions"
HELPERS = ("suno-helper", "distrokid-helper", "community-helper")
PRIMITIVES = ("alert.tsx", "button.tsx", "card.tsx", "select.tsx")


def test_shared_ui_package_owns_public_primitives_and_theme() -> None:
    package = json.loads((EXTENSIONS / "shared-ui/package.json").read_text())

    assert package["name"] == "@youtube-automation/ui"
    assert package["exports"] == {
        ".": "./src/index.ts",
        "./theme.css": "./src/theme.css",
    }
    assert set(package["dependencies"]) == {
        "@radix-ui/react-slot",
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
        "Select",
        "cn",
    ):
        assert public_symbol in index


def test_helpers_depend_on_shared_ui_without_local_primitive_copies() -> None:
    for helper_name in HELPERS:
        helper = EXTENSIONS / helper_name
        package = json.loads((helper / "package.json").read_text())

        assert package["dependencies"]["@youtube-automation/ui"] == "workspace:*"
        assert not (helper / "lib/utils.ts").exists()
        for primitive in PRIMITIVES:
            assert not (helper / f"components/ui/{primitive}").exists()


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
