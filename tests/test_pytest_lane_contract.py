"""pytest fast / repository-contract / slow lane classification contracts."""

from __future__ import annotations

import ast
import subprocess
import sys

from tests.helpers.paths import REPO_ROOT

ROOT = REPO_ROOT
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
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *SLOW_NODE_IDS],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    collected = {line for line in result.stdout.splitlines() if line.startswith("tests/")}

    assert result.returncode == 0, result.stdout + result.stderr
    assert collected == set(SLOW_NODE_IDS)


def test_ci_runs_the_full_pytest_suite_without_lane_filters() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "nix develop --command uv run pytest -n auto" in workflow
    assert '-m "not repo_contract and not slow"' not in workflow


def test_development_documents_each_pytest_lane_command() -> None:
    development = (ROOT / "docs/development.md").read_text(encoding="utf-8")

    for expression in ('-m "not repo_contract and not slow"', "-m repo_contract", "-m slow"):
        assert expression in development
