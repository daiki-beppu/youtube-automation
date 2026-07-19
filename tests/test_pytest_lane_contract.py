"""pytest fast / repository-contract / slow lane classification contracts."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
TESTS = ROOT / "tests"
CONFTEST = TESTS / "conftest.py"


def _registry_value(name: str) -> frozenset[str] | tuple[str, ...]:
    tree = ast.parse(CONFTEST.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "frozenset":
            assert len(value.args) == 1
            return frozenset(ast.literal_eval(value.args[0]))
        parsed = ast.literal_eval(value)
        assert isinstance(parsed, tuple)
        return parsed
    raise AssertionError(f"pytest lane registry is missing {name}")


REPO_CONTRACT_MODULES = _registry_value("REPO_CONTRACT_MODULES")
SLOW_MODULES = _registry_value("SLOW_MODULES")
SLOW_NODE_IDS = _registry_value("SLOW_NODE_IDS")


def test_registered_lane_modules_exist() -> None:
    registered = REPO_CONTRACT_MODULES | SLOW_MODULES
    missing = sorted(name for name in registered if not (TESTS / name).is_file())
    assert not missing, f"pytest lane registry points to missing modules: {missing}"


def test_slow_node_ids_reference_existing_modules_and_tests() -> None:
    for node_id in SLOW_NODE_IDS:
        module_path, separator, test_name = node_id.partition("::")
        assert separator and test_name, f"slow node id must select a test: {node_id}"
        source = ROOT / module_path
        assert source.is_file(), f"slow node module does not exist: {module_path}"
        assert test_name.split("::")[-1] in source.read_text(encoding="utf-8"), (
            f"slow node test name is absent from {module_path}: {test_name}"
        )


def test_lane_commands_keep_ci_full_suite_unfiltered() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    development = (ROOT / "docs/development.md").read_text(encoding="utf-8")

    assert "nix develop --command uv run pytest -n auto" in workflow
    assert '-m "not repo_contract and not slow"' not in workflow
    for expression in ('-m "not repo_contract and not slow"', "-m repo_contract", "-m slow"):
        assert expression in development
