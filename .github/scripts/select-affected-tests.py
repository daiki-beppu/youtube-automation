#!/usr/bin/env python3
"""変更 path から影響する pytest module の保守的な実行計画を作る。"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath
from typing import Final

ALL = None
SOURCE_PREFIX: Final = "src/youtube_automation/"
TEST_PREFIX: Final = "tests/"
FAIL_SAFE_EXACT: Final = frozenset(
    {
        "tests/conftest.py",
        "pyproject.toml",
        "uv.lock",
        "flake.nix",
        "flake.lock",
        "src/youtube_automation/__init__.py",
        ".github/scripts/select-affected-tests.py",
    }
)
FAIL_SAFE_PREFIXES: Final = ("tests/helpers/", "tests/fixtures/")
CHANGELOG_FRAGMENT_PREFIX: Final = "changelog.d/"
CHANGELOG_FRAGMENT_SUFFIX: Final = ".md"
CHANGELOG_FRAGMENT_TESTS: Final = (
    "tests/commands/system/test_changelog_compile.py",
    "tests/repo/test_changelog_ci_contract.py",
)
PATH_TEST_MAP: Final = (
    (".github/workflows/", ("tests/repo/test_actions_parallel_workflows.py",)),
    (
        "docs/adr/",
        (
            "tests/repo/test_b6_integration_contract.py",
            "tests/repo/test_site_repository_contract.py",
        ),
    ),
    ("CHANGELOG.md", ("tests/repo/test_changelog_ci_contract.py",)),
)


def _is_test_module(path: Path) -> bool:
    return path.suffix == ".py" and (path.name.startswith("test_") or path.name.endswith("_test.py"))


def _module_name(relative: str) -> str | None:
    if not relative.endswith(".py"):
        return None
    if relative.startswith("src/"):
        relative = relative.removeprefix("src/")
    elif relative.startswith("tests/"):
        relative = relative.removeprefix("tests/")
    else:
        return None
    parts = PurePosixPath(relative).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _imports(path: Path, module: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_module = node.module or ""
            if node.level:
                package = module if path.name == "__init__.py" else module.rpartition(".")[0]
                imported_module = importlib.util.resolve_name(f"{'.' * node.level}{imported_module}", package)
            if imported_module:
                imported.add(imported_module)
                imported.update(f"{imported_module}.{alias.name}" for alias in node.names)
    return imported


def _validate_path(repository: Path, changed: str) -> bool:
    if not changed or "\\" in changed:
        return False
    pure = PurePosixPath(changed)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != changed:
        return False
    return (repository / pure).is_file()


def _mapped_tests(changed: str) -> tuple[str, ...] | None:
    if changed.startswith(CHANGELOG_FRAGMENT_PREFIX) and changed.endswith(CHANGELOG_FRAGMENT_SUFFIX):
        return CHANGELOG_FRAGMENT_TESTS
    for pattern, targets in PATH_TEST_MAP:
        if (pattern.endswith("/") and changed.startswith(pattern)) or changed == pattern:
            return targets
    return None


def select_targets(repository: Path, changed_paths: list[str]) -> tuple[str, ...] | None:
    """Return sorted test targets, or ``None`` for the ALL fail-safe plan."""
    changed_paths = list(dict.fromkeys(changed_paths))
    if not changed_paths:
        return ALL
    if any(path in FAIL_SAFE_EXACT or path.startswith(FAIL_SAFE_PREFIXES) for path in changed_paths):
        return ALL

    try:
        source_paths = sorted((repository / "src/youtube_automation").rglob("*.py"))
        test_paths = sorted((repository / "tests").rglob("*.py"))
        module_paths = [*source_paths, *test_paths]
        module_by_path = {
            path.relative_to(repository).as_posix(): _module_name(path.relative_to(repository).as_posix())
            for path in module_paths
        }
        importers: dict[str, set[str]] = defaultdict(set)
        for path in module_paths:
            relative = path.relative_to(repository).as_posix()
            importer = module_by_path[relative]
            if importer is None:
                continue
            for imported in _imports(path, importer):
                importers[imported].add(importer)

        path_by_module = {module: relative for relative, module in module_by_path.items() if module is not None}
        selected: set[str] = set()
        changed_modules: list[str] = []
        for changed in changed_paths:
            if not _validate_path(repository, changed):
                return ALL
            mapped = _mapped_tests(changed)
            if mapped is not None:
                if not all((repository / target).is_file() for target in mapped):
                    return ALL
                selected.update(mapped)
                continue
            path = repository / changed
            if changed.startswith(TEST_PREFIX) and _is_test_module(path):
                selected.add(changed)
            elif changed.startswith(SOURCE_PREFIX) and changed.endswith(".py"):
                module = module_by_path.get(changed)
                if module is None:
                    return ALL
                changed_modules.append(module)
                source_relative = PurePosixPath(changed.removeprefix(SOURCE_PREFIX))
                mirror_name = (
                    "test___init__.py" if source_relative.name == "__init__.py" else f"test_{source_relative.name}"
                )
                mirror = PurePosixPath("tests", source_relative.parent, mirror_name).as_posix()
                if (repository / mirror).is_file():
                    selected.add(mirror)
            else:
                return ALL

        queue = deque(changed_modules)
        visited = set(changed_modules)
        while queue:
            module = queue.popleft()
            for importer in sorted(importers.get(module, ())):
                if importer in visited:
                    continue
                visited.add(importer)
                queue.append(importer)
                relative = path_by_module.get(importer)
                if relative and relative.startswith(TEST_PREFIX):
                    path = repository / relative
                    if _is_test_module(path):
                        selected.add(relative)
        if not selected:
            return ALL
        if not all((repository / target).is_file() for target in selected):
            return ALL
        return tuple(sorted(selected))
    except (OSError, SyntaxError, UnicodeError, ValueError):
        return ALL


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("changed_paths", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        changed = arguments.changed_paths.read_text(encoding="utf-8").splitlines()
        plan = select_targets(Path.cwd(), changed)
    except (OSError, UnicodeError):
        plan = ALL
    if arguments.format == "json":
        payload = {
            "mode": "all" if plan is ALL else "selected",
            "targets": [] if plan is ALL else list(plan),
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    elif plan is ALL:
        print("ALL")
    else:
        print(*plan, sep="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
