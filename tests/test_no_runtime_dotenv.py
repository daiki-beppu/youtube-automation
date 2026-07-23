"""チャンネルルート dotenv を production runtime へ再導入させない contract test."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def test_production_python_does_not_import_or_load_dotenv() -> None:
    forbidden = ("from dotenv import", "import dotenv", "load_dotenv(", "find_dotenv(")
    violations: list[str] = []

    for path in sorted((_ROOT / "src").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in source:
                violations.append(f"{path.relative_to(_ROOT)}: {token}")

    assert violations == []


def test_python_dotenv_is_not_a_package_dependency() -> None:
    assert "python-dotenv" not in (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "python-dotenv"' not in (_ROOT / "uv.lock").read_text(encoding="utf-8")
