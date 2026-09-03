"""pytest fast / repository-contract / slow lane classification contracts."""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.helpers.paths import REPO_ROOT
from tests.helpers.tests_tree import exclusive_tests_tree_lock, shared_tests_tree_lock

ROOT = REPO_ROOT
TESTS = ROOT / "tests"
CONFTEST = TESTS / "conftest.py"
_RELOCATION_PROBE_PREFIX = "pytest-lane-relocation-"


def _registry_ast_value(name: str) -> ast.expr:
    tree = ast.parse(CONFTEST.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        return node.value
    raise AssertionError(f"pytest lane registry is missing {name}")


def _module_registry_value(name: str) -> frozenset[str] | tuple[str, ...]:
    value = _registry_ast_value(name)
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "frozenset":
        assert len(value.args) == 1
        parsed = ast.literal_eval(value.args[0])
        assert isinstance(parsed, (list, tuple, set, frozenset))
        assert all(isinstance(module_name, str) for module_name in parsed)
        return frozenset(parsed)
    parsed = ast.literal_eval(value)
    assert isinstance(parsed, tuple)
    assert all(isinstance(module_name, str) for module_name in parsed)
    return parsed


def _slow_node_registry_value(name: str) -> tuple[tuple[str, str], ...]:
    parsed = ast.literal_eval(_registry_ast_value(name))
    assert isinstance(parsed, tuple)
    assert all(
        isinstance(entry, tuple) and len(entry) == 2 and all(isinstance(part, str) for part in entry)
        for entry in parsed
    )
    return parsed


REPO_CONTRACT_MODULES = _module_registry_value("REPO_CONTRACT_MODULES")
SLOW_MODULES = _module_registry_value("SLOW_MODULES")
SLOW_NODE_IDS = _slow_node_registry_value("SLOW_NODE_IDS")


def _registered_lane_module_names() -> frozenset[str]:
    return frozenset(REPO_CONTRACT_MODULES | SLOW_MODULES) | frozenset(module_name for module_name, _ in SLOW_NODE_IDS)


def _source_module_paths(module_name: str) -> tuple[Path, ...]:
    with shared_tests_tree_lock():
        return _source_module_paths_without_lock(module_name)


def _source_module_paths_without_lock(module_name: str) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in TESTS.rglob(module_name)
            if path.is_file()
            and path.suffix == ".py"
            and not any(parent.name.startswith(_RELOCATION_PROBE_PREFIX) for parent in path.parents)
        )
    )


def _slow_node_paths_without_lock() -> tuple[str, ...]:
    return tuple(
        f"{path.relative_to(ROOT)}::{test_identifier}"
        for module_name, test_identifier in SLOW_NODE_IDS
        for path in _source_module_paths_without_lock(module_name)
    )


def test_registered_lane_modules_exist() -> None:
    """REQ-3042-03: registered lane modules exist anywhere below the tests root."""
    missing = sorted(name for name in _registered_lane_module_names() if not _source_module_paths(name))
    assert not missing, f"pytest lane registry points to missing modules: {missing}"


def test_registered_slow_nodes_belong_to_slow_lane() -> None:
    """REQ-3042-01a: every registered slow node belongs to the slow lane."""
    with shared_tests_tree_lock():
        expected = _slow_node_paths_without_lock()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-m",
                "slow",
                *expected,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    collected = {line for line in result.stdout.splitlines() if line.startswith("tests/")}

    assert result.returncode == 0, result.stdout + result.stderr
    assert collected == set(expected)


def test_slow_node_registry_is_independent_of_module_path() -> None:
    """REQ-3042-01b: slow node registry values contain no filesystem path."""
    assert all(
        "/" not in module_name and module_name.endswith(".py") and test_identifier
        for module_name, test_identifier in SLOW_NODE_IDS
    )


def test_slow_marker_survives_nested_module_relocation() -> None:
    """REQ-3042-01c: a registered slow node remains slow in a nested module path."""
    module_name, test_identifier = SLOW_NODE_IDS[0]

    # probe directory の作成から後始末までを write lock の内側に収める。実ツリーを
    # 走査する reader（select-affected / layout 契約）から見て、この窓の外では
    # `tests/` が常に本来の姿でなければならない。
    with (
        exclusive_tests_tree_lock(),
        tempfile.TemporaryDirectory(prefix=_RELOCATION_PROBE_PREFIX, dir=TESTS) as temp_dir,
    ):
        relocated = Path(temp_dir) / "nested" / module_name
        relocated.parent.mkdir()
        source = _source_module_paths_without_lock(module_name)
        assert len(source) == 1, f"slow node module must resolve uniquely: {module_name} -> {source}"
        shutil.move(source[0], relocated)
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "--collect-only",
                    "-q",
                    "-m",
                    "slow",
                    str(relocated.relative_to(ROOT)),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            shutil.move(relocated, source[0])

    relocated_node = f"{relocated.relative_to(ROOT)}::{test_identifier}"
    collected = {line for line in result.stdout.splitlines() if line.startswith("tests/")}
    assert result.returncode == 0, result.stdout + result.stderr
    assert relocated_node in collected


def test_registered_lane_module_basenames_are_unique_source_modules() -> None:
    """REQ-3042-04: each registered basename resolves to one Python source module."""
    candidates = {name: _source_module_paths(name) for name in _registered_lane_module_names()}
    duplicates = {name: paths for name, paths in candidates.items() if len(paths) > 1}

    assert not duplicates, f"registered module basenames are ambiguous: {duplicates}"


def test_slow_node_ids_reference_existing_modules_and_tests() -> None:
    """REQ-3042-02: every registered slow node resolves to one collected test."""
    with shared_tests_tree_lock():
        expected = _slow_node_paths_without_lock()
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", *expected],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    collected = {line for line in result.stdout.splitlines() if line.startswith("tests/")}

    assert result.returncode == 0, result.stdout + result.stderr
    assert collected == set(expected)


def test_ci_main_push_and_fail_safe_run_exhaustive_non_overlapping_lanes() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert '[ "$EVENT_NAME" = "pull_request" ]' in workflow
    assert '[ "$mode" = "selected" ]' in workflow
    assert workflow.count('-m "not repo_contract and not slow"') == 1
    assert workflow.count('-m "repo_contract and not slow"') == 1
    assert workflow.count("-m slow") == 1


def test_development_documents_each_pytest_lane_command() -> None:
    development = (ROOT / "docs/development.md").read_text(encoding="utf-8")

    for expression in (
        '-m "not repo_contract and not slow"',
        '-m "repo_contract and not slow"',
        "-m slow",
    ):
        assert expression in development


def test_development_documents_local_selection_and_main_full_safety_net() -> None:
    development = (ROOT / "docs/development.md").read_text(encoding="utf-8")

    assert "python .github/scripts/run-affected-tests.py" in development
    assert "main" in development
    assert "選別漏れ" in development
    assert "marker" in development


def test_development_documents_position_independent_lane_registry() -> None:
    """REQ-3042-07b: development docs describe registry placement independence."""
    development = (ROOT / "docs/development.md").read_text(encoding="utf-8")

    assert "module は basename" in development
    assert "配置に依存しない" in development
    assert "同じ basename の source module は登録できない" in development
