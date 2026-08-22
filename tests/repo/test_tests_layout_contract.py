import ast
import re
from pathlib import Path

from tests.helpers.paths import FIXTURES_DIR, REPO_ROOT, TESTS_DIR
from tests.helpers.tests_tree import shared_tests_tree_lock

ROOT_TEST_ALLOWLIST = frozenset(
    {
        "test_analytics_cli_integration.py",
        "test_b3_domain_migration_contract.py",
        "test_b4_auth_resource_contract.py",
        "test_b4_reorganization_contract.py",
        "test_bench_cost_tracker.py",
        "test_channel_new_fetch_branding_snapshot.py",
        "test_cli_help_contract.py",
        "test_cli_stdio.py",
        "test_codex_image_batch.py",
        "test_codex_thumbnail_routing.py",
        "test_community_draft_batch.py",
        "test_conftest_isolation.py",
        "test_entrypoints.py",
        "test_generate_videos_script.py",
        "test_oauth_onboarding_contract.py",
        "test_package_version.py",
        "test_streaming_healthcheck.py",
        "test_wf_new_analytics_fallback_skill_contract.py",
    }
)
LAYOUT_EXCEPTIONS = frozenset({"repo", "integration", "contracts", "helpers", "fixtures"})
SOURCE_ROOT = REPO_ROOT / "src" / "youtube_automation"


def test_test_path_constants_are_stable() -> None:
    assert isinstance(REPO_ROOT, Path)
    assert isinstance(TESTS_DIR, Path)
    assert isinstance(FIXTURES_DIR, Path)
    assert (REPO_ROOT / "pyproject.toml").is_file()
    assert TESTS_DIR == REPO_ROOT / "tests"
    assert FIXTURES_DIR == TESTS_DIR / "fixtures"


def _assignment_bindings(node: ast.AST) -> list[tuple[ast.Name, ast.expr]]:
    if isinstance(node, ast.Assign):
        bindings = []
        for target in node.targets:
            bindings.extend(_target_bindings(target, node.value))
        return bindings
    if isinstance(node, ast.AnnAssign):
        if node.value is None:
            return []
        return _target_bindings(node.target, node.value)
    return []


def _target_bindings(target: ast.expr, value: ast.expr) -> list[tuple[ast.Name, ast.expr]]:
    if isinstance(target, ast.Name):
        return [(target, value)]
    if isinstance(target, (ast.List, ast.Tuple)) and isinstance(value, (ast.List, ast.Tuple)):
        bindings = []
        for nested_target, nested_value in zip(target.elts, value.elts, strict=False):
            bindings.extend(_target_bindings(nested_target, nested_value))
        return bindings
    return []


def _source_kind(
    value: ast.expr,
    path_names: set[str],
    pathlib_names: set[str],
    file_names: set[str],
) -> str | None:
    if isinstance(value, ast.Name):
        if value.id in path_names:
            return "path"
        if value.id in pathlib_names:
            return "pathlib"
        if value.id in file_names:
            return "file"
    if (
        isinstance(value, ast.Attribute)
        and value.attr == "Path"
        and isinstance(value.value, ast.Name)
        and value.value.id in pathlib_names
    ):
        return "path"
    if _contains_name(value, file_names):
        return "file"
    return None


def _contains_name(value: ast.AST, names: set[str]) -> bool:
    return any(isinstance(node, ast.Name) and node.id in names for node in ast.walk(value))


def _path_aliases(tree: ast.AST) -> tuple[set[str], set[str], set[str]]:
    path_names = {"Path"}
    pathlib_names = {"pathlib"}
    file_names = {"__file__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "pathlib":
            for alias in node.names:
                if alias.name == "Path":
                    path_names.add(alias.asname or alias.name)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pathlib":
                    pathlib_names.add(alias.asname or alias.name)

    aliases_changed = True
    while aliases_changed:
        aliases_changed = False
        for node in ast.walk(tree):
            for target, value in _assignment_bindings(node):
                source_kind = _source_kind(value, path_names, pathlib_names, file_names)
                if source_kind is None:
                    continue
                destination = {
                    "path": path_names,
                    "pathlib": pathlib_names,
                    "file": file_names,
                }[source_kind]
                if target.id not in destination:
                    destination.add(target.id)
                    aliases_changed = True
    return path_names, pathlib_names, file_names


def _uses_path_from_file(tree: ast.AST) -> bool:
    path_names, pathlib_names, file_names = _path_aliases(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        is_path_constructor = isinstance(node.func, ast.Name) and node.func.id in path_names
        is_module_path = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "Path"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in pathlib_names
        )
        arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
        if (is_path_constructor or is_module_path) and any(
            _contains_name(argument, file_names) for argument in arguments
        ):
            return True
    return False


def test_tests_do_not_resolve_paths_from_file_location() -> None:
    violations = []
    allowed = TESTS_DIR / "helpers" / "paths.py"

    with shared_tests_tree_lock():
        for path in TESTS_DIR.rglob("*.py"):
            if path == allowed:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if _uses_path_from_file(tree):
                violations.append(path.relative_to(REPO_ROOT).as_posix())

    assert violations == []


def test_path_from_file_detection_covers_aliases() -> None:
    examples = (
        "from pathlib import Path as P\nP(__file__).resolve()",
        "import pathlib as pl\npl." + "Path" + "(__file__).resolve()",
        "from pathlib import Path\nP = Path\nP(__file__).resolve()",
        "from pathlib import Path\nP: type[Path] = Path\nP(__file__).resolve()",
        "from pathlib import Path\nP, marker = Path, None\nP(__file__).resolve()",
        "from pathlib import Path\n[P, marker] = [Path, None]\nP(__file__).resolve()",
        "import pathlib\npl = pathlib\npl." + "Path" + "(__file__).resolve()",
        "import pathlib\npl, marker = pathlib, None\npl." + "Path" + "(__file__).resolve()",
        "import pathlib\n[pl, marker] = [pathlib, None]\npl." + "Path" + "(__file__).resolve()",
        "import pathlib as pl\nP = pl.Path\nP(__file__).resolve()",
        "from pathlib import Path\nfile_path = __file__\nPath(file_path).resolve()",
        "from pathlib import Path\nfile_path, marker = __file__, None\nPath(file_path).resolve()",
        "from pathlib import Path\n[file_path, marker] = [__file__, None]\nPath(file_path).resolve()",
        "from pathlib import Path\nPath(str(__file__)).resolve()",
        "from pathlib import Path\nPath(__file__ + '').resolve()",
        "from pathlib import Path\nfile_path = str(__file__)\nPath(file_path).resolve()",
        "import pathlib as pl\npl." + "Path" + "(str(__file__)).resolve()",
        "import pathlib as pl\npl." + "Path" + "(__file__ + '').resolve()",
        "import pathlib as pl\nfile_path = str(__file__)\npl." + "Path" + "(file_path).resolve()",
    )

    for source in examples:
        assert _uses_path_from_file(ast.parse(source))


def test_path_from_file_detection_ignores_annotation_without_value() -> None:
    assert not _uses_path_from_file(ast.parse("from pathlib import Path\nP: type[Path]\n"))


def test_layout_contract_is_registered_in_repo_contract_lane() -> None:
    conftest = (TESTS_DIR / "conftest.py").read_text(encoding="utf-8")
    tree = ast.parse(conftest)
    registry_entries = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "REPO_CONTRACT_MODULES" for target in node.targets):
            continue
        assert isinstance(node.value, ast.Call)
        assert isinstance(node.value.func, ast.Name)
        assert node.value.func.id == "frozenset"
        registry_entries = ast.literal_eval(node.value.args[0])
        break

    assert registry_entries is not None
    assert "test_tests_layout_contract.py" in registry_entries


def _source_module_path(module_name: str) -> Path | None:
    prefix = "youtube_automation."
    if not module_name.startswith(prefix):
        return None
    relative = Path(*module_name.removeprefix(prefix).split("."))
    module_path = SOURCE_ROOT / relative.with_suffix(".py")
    package_path = SOURCE_ROOT / relative / "__init__.py"
    if module_path.is_file():
        return module_path
    if package_path.is_file():
        return package_path
    return None


def _source_owner_candidates(tree: ast.AST, mirror_package: tuple[str, ...]) -> set[Path]:
    candidates = set()
    for module in _imported_source_modules(tree):
        owner = _source_module_path(module)
        if owner is None:
            continue
        owner_parts = owner.relative_to(SOURCE_ROOT).with_suffix("").parts
        if owner_parts[: len(mirror_package)] == mirror_package:
            candidates.add(owner)
    return candidates


def _imported_source_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            if node.module.startswith("youtube_automation"):
                modules.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if re.fullmatch(r"youtube_automation(?:\.[a-zA-Z_]\w*)+", node.value):
                modules.add(node.value)
    return modules


def _is_pytest_test_module(path: Path) -> bool:
    return path.is_file() and (path.name.startswith("test_") or path.name.endswith("_test.py"))


def _pytest_test_modules(root: Path) -> list[Path]:
    return [path for path in root.rglob("*.py") if _is_pytest_test_module(path)]


def _mirrored_test_paths() -> list[Path]:
    return [
        path
        for path in _pytest_test_modules(TESTS_DIR)
        if len(path.relative_to(TESTS_DIR).parts) > 1 and path.relative_to(TESTS_DIR).parts[0] not in LAYOUT_EXCEPTIONS
    ]


def _exact_source_owner_paths(test_path: Path) -> tuple[Path, Path]:
    relative = test_path.relative_to(TESTS_DIR)
    mirror_package = relative.parts[:-1]
    module_name = test_path.stem.removeprefix("test_")
    exact_owner = SOURCE_ROOT.joinpath(*mirror_package, f"{module_name}.py")
    package_owner = SOURCE_ROOT.joinpath(*mirror_package, module_name, "__init__.py")
    return exact_owner, package_owner


def test_root_test_modules_match_allowlist() -> None:
    with shared_tests_tree_lock():
        actual = frozenset(path.name for path in _pytest_test_modules(TESTS_DIR) if path.parent == TESTS_DIR)
    assert actual == ROOT_TEST_ALLOWLIST


def test_test_layers_match_source_layers() -> None:
    source_layers = frozenset(path.name for path in SOURCE_ROOT.iterdir() if (path / "__init__.py").is_file())
    with shared_tests_tree_lock():
        test_layers = {
            path.relative_to(TESTS_DIR).parts[0]
            for path in TESTS_DIR.iterdir()
            if path.is_dir() and _pytest_test_modules(path)
        }
    mirrored_layers = test_layers - LAYOUT_EXCEPTIONS
    assert mirrored_layers <= source_layers


def test_exact_source_owner_keeps_nested_mirror_package() -> None:
    exact_owner, package_owner = _exact_source_owner_paths(
        TESTS_DIR / "infrastructure" / "runtime" / "test_time_utils.py"
    )

    assert exact_owner == SOURCE_ROOT / "infrastructure" / "runtime" / "time_utils.py"
    assert package_owner == (SOURCE_ROOT / "infrastructure" / "runtime" / "time_utils" / "__init__.py")
    assert exact_owner.is_file()


def test_source_owner_candidates_stay_within_mirror_package() -> None:
    tree = ast.parse(
        "from youtube_automation.application.analytics import report\n"
        "from youtube_automation.application.comments import generator\n"
    )

    candidates = _source_owner_candidates(tree, ("application", "analytics"))

    assert candidates == {SOURCE_ROOT / "application" / "analytics" / "__init__.py"}


def test_mirrored_test_modules_have_source_owner() -> None:
    violations = []
    with shared_tests_tree_lock():
        for test_path in _mirrored_test_paths():
            relative = test_path.relative_to(TESTS_DIR)
            mirror_package = relative.parts[:-1]
            exact_owner, package_owner = _exact_source_owner_paths(test_path)
            if exact_owner.is_file() or package_owner.is_file():
                continue

            tree = ast.parse(test_path.read_text(encoding="utf-8"), filename=str(test_path))
            candidates = _source_owner_candidates(tree, mirror_package)
            if not candidates:
                violations.append(relative.as_posix())

    assert violations == []
