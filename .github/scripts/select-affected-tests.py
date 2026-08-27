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
# prefix エントリと完全一致エントリは合成される（`_mapped_tests` が全マッチを union する）。
# prefix 側には配下を横断して検証する test だけを置き、ファイル固有の契約は完全一致側へ分ける。
# `tests/repo/test_select_affected_tests.py` を `.github/` の両 prefix に含めるのは、
# 対応表のドリフトを検出する完全性契約テストを、対象ドメインを変更した PR 自身で走らせるため。
PATH_TEST_MAP: Final = (
    (
        ".github/workflows/",
        (
            "tests/repo/test_actions_parallel_workflows.py",
            "tests/repo/test_github_actions_pinning.py",
            "tests/repo/test_select_affected_tests.py",
        ),
    ),
    (
        ".github/workflows/ci.yml",
        (
            "tests/repo/test_changelog_ci_contract.py",
            "tests/repo/test_evals_workflow.py",
            "tests/repo/test_pyscn_diff_gate_contract.py",
            "tests/repo/test_pytest_lane_contract.py",
            "tests/repo/test_release_notes_contract.py",
            "tests/repo/test_skill_catalog_removal.py",
        ),
    ),
    (".github/workflows/ci-autofix.yml", ("tests/repo/test_ci_autofix_workflow.py",)),
    (".github/workflows/code-review.yml", ("tests/repo/test_code_review_workflow.py",)),
    (
        ".github/workflows/dashboard.yml",
        ("tests/contracts/architecture/test_repository_reorganization_contract.py",),
    ),
    (".github/workflows/evals.yml", ("tests/repo/test_evals_workflow.py",)),
    (".github/workflows/extensions.yml", ("tests/repo/test_extension_package_manager_contract.py",)),
    (
        ".github/workflows/release-extensions.yml",
        (
            "tests/repo/test_extension_package_manager_contract.py",
            "tests/repo/test_release_extensions_workflow.py",
            "tests/repo/test_verify_extensions_script.py",
        ),
    ),
    (
        ".github/workflows/site.yml",
        (
            "tests/repo/test_site_repository_contract.py",
            "tests/repo/test_skill_page_generation_contract.py",
        ),
    ),
    (".github/scripts/", ("tests/repo/test_select_affected_tests.py",)),
    (
        ".github/scripts/any-usage-gate.sh",
        (
            "tests/repo/test_any_usage_gate.py",
            "tests/repo/test_takt_workflow_contract.py",
        ),
    ),
    # resolver / cleaner は any-usage-gate.sh から subprocess で呼ばれるだけで
    # 名指しの参照を持たないため、gate 本体の E2E テストへ対応付ける。
    (".github/scripts/any_usage_python_resolver.py", ("tests/repo/test_any_usage_gate.py",)),
    (".github/scripts/any_usage_ts_line_cleaner.py", ("tests/repo/test_any_usage_gate.py",)),
    (".github/scripts/classify-ci-paths.sh", ("tests/repo/test_actions_parallel_workflows.py",)),
    (".github/scripts/pyscn-diff-gate.py", ("tests/repo/test_pyscn_diff_gate_contract.py",)),
    (
        ".github/scripts/run-affected-tests.py",
        (
            "tests/repo/test_pytest_lane_contract.py",
            "tests/repo/test_takt_workflow_contract.py",
        ),
    ),
    (
        ".github/scripts/validate-changelog-fragments.py",
        ("tests/repo/test_changelog_ci_contract.py",),
    ),
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


def _dynamic_import_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """`importlib` module / `import_module` 関数に束縛された名前を alias 込みで集める。"""
    module_names = {"importlib"}
    function_names = {"import_module", "__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib" and alias.asname:
                    module_names.add(alias.asname)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module" and alias.asname:
                    function_names.add(alias.asname)
    return module_names, function_names


def _dynamic_import_argument(
    node: ast.AST, module_names: set[str], function_names: set[str]
) -> tuple[bool, ast.expr | None]:
    """動的 import 呼び出しかどうかと、その module 名引数（特定できなければ ``None``）を返す。"""
    if not isinstance(node, ast.Call):
        return False, None
    function = node.func
    if isinstance(function, ast.Name):
        matched = function.id in function_names
    elif isinstance(function, ast.Attribute):
        matched = (
            function.attr == "import_module"
            and isinstance(function.value, ast.Name)
            and function.value.id in module_names
        )
    else:
        matched = False
    if not matched:
        return False, None
    if node.args:
        return True, node.args[0]
    for keyword in node.keywords:
        if keyword.arg == "name":
            return True, keyword.value
    # `import_module(**kwargs)` のように引数を特定できない呼び出しも動的 import として扱う。
    return True, None


def _imports(path: Path, module: str) -> tuple[set[str], bool]:
    """静的 import と文字列リテラルの動的 import を集め、解決不能な動的 import の有無を返す。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_names, function_names = _dynamic_import_names(tree)
    imported: set[str] = set()
    has_unresolved_dynamic = False
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
        else:
            is_dynamic_import, argument = _dynamic_import_argument(node, module_names, function_names)
            if not is_dynamic_import:
                continue
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                imported.add(argument.value)
            else:
                has_unresolved_dynamic = True
    return imported, has_unresolved_dynamic


def _validate_path(repository: Path, changed: str) -> bool:
    if not changed or "\\" in changed:
        return False
    pure = PurePosixPath(changed)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != changed:
        return False
    return (repository / pure).is_file()


def _mapped_tests(changed: str) -> tuple[str, ...] | None:
    """マッチした**全**エントリの対象を合成して返す。未マッチなら ``None``。

    最初のマッチで打ち切ると prefix と完全一致のどちらか片方しか効かず、
    `.github/workflows/ci.yml` の変更が横断 test 1 件にしか対応付かない（#4658）。
    """
    if changed.startswith(CHANGELOG_FRAGMENT_PREFIX) and changed.endswith(CHANGELOG_FRAGMENT_SUFFIX):
        return CHANGELOG_FRAGMENT_TESTS
    matched: set[str] = set()
    for pattern, targets in PATH_TEST_MAP:
        if (pattern.endswith("/") and changed.startswith(pattern)) or changed == pattern:
            matched.update(targets)
    return tuple(sorted(matched)) if matched else None


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
        wildcard_importers: set[str] = set()
        for path in module_paths:
            relative = path.relative_to(repository).as_posix()
            importer = module_by_path[relative]
            if importer is None:
                continue
            imported_names, has_unresolved_dynamic = _imports(path, importer)
            for imported in imported_names:
                importers[imported].add(importer)
            if has_unresolved_dynamic:
                # 文字列リテラルへ解決できない動的 import は依存先を静的に特定できない。
                # 保守的に「どの source 変更でも影響を受ける」扱いにする。
                wildcard_importers.add(importer)

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

        affected_roots = list(changed_modules)
        if changed_modules:
            # source 側 wildcard は BFS 起点にも加え、それを import する module 経由の
            # test まで transitively 選定する。test 側 wildcard は直接選定する。
            changed_module_set = set(changed_modules)
            for wildcard in sorted(wildcard_importers):
                if wildcard not in changed_module_set:
                    affected_roots.append(wildcard)
                relative = path_by_module.get(wildcard)
                if relative and relative.startswith(TEST_PREFIX) and _is_test_module(repository / relative):
                    selected.add(relative)
        queue = deque(affected_roots)
        visited = set(affected_roots)
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
