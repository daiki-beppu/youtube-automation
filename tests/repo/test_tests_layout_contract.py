import ast
from pathlib import Path

from tests.helpers.paths import FIXTURES_DIR, REPO_ROOT, TESTS_DIR


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
