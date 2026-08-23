from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from tests.helpers.tests_tree import shared_tests_tree_lock

SCRIPT = REPO_ROOT / ".github/scripts/select-affected-tests.py"


def _load_selector():
    spec = importlib.util.spec_from_file_location("select_affected_tests", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(repository: Path, relative: str, content: str = "") -> None:
    path = repository / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _synthetic_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    _write(repository, "src/youtube_automation/__init__.py")
    _write(repository, "src/youtube_automation/core/__init__.py")
    _write(repository, "src/youtube_automation/core/leaf.py", "VALUE = 1\n")
    _write(
        repository,
        "src/youtube_automation/core/middle.py",
        "from youtube_automation.core.leaf import VALUE\n",
    )
    _write(repository, "src/youtube_automation/other.py", "VALUE = 2\n")
    _write(
        repository,
        "tests/core/test_middle.py",
        "from youtube_automation.core.middle import VALUE\n",
    )
    _write(repository, "tests/core/test_leaf.py", "def test_leaf():\n    assert True\n")
    _write(
        repository,
        "tests/test_direct.py",
        "from youtube_automation.core.leaf import VALUE\n",
    )
    _write(
        repository,
        "tests/test_other.py",
        "from youtube_automation.other import VALUE\n",
    )
    _write(repository, "tests/repo/test_actions_parallel_workflows.py")
    _write(repository, "tests/repo/test_changelog_ci_contract.py")
    _write(repository, "tests/commands/system/test_changelog_compile.py")
    _write(repository, "tests/repo/test_b6_integration_contract.py")
    _write(repository, "tests/repo/test_site_repository_contract.py")
    _write(repository, ".github/workflows/ci.yml")
    _write(repository, "docs/adr/0024-example.md")
    _write(repository, "CHANGELOG.md")
    _write(repository, "changelog.d/4526-example.fixed.md")
    _write(repository, "changelog.d/notes.txt")
    return repository


def test_source_change_selects_only_direct_and_transitive_importers(tmp_path: Path) -> None:
    selector = _load_selector()
    repository = _synthetic_repository(tmp_path)

    result = selector.select_targets(repository, ["src/youtube_automation/core/leaf.py"])

    assert result == (
        "tests/core/test_leaf.py",
        "tests/core/test_middle.py",
        "tests/test_direct.py",
    )


@pytest.mark.parametrize(
    "changed_path",
    [
        "tests/conftest.py",
        "tests/helpers/factory.py",
        "tests/fixtures/config.json",
        "pyproject.toml",
        "uv.lock",
        "flake.nix",
        "flake.lock",
        "src/youtube_automation/__init__.py",
        ".github/scripts/select-affected-tests.py",
    ],
)
def test_fail_safe_paths_select_all(tmp_path: Path, changed_path: str) -> None:
    selector = _load_selector()
    repository = _synthetic_repository(tmp_path)

    assert selector.select_targets(repository, [changed_path]) is None


def test_workflow_adr_changelog_and_direct_test_use_explicit_mapping(tmp_path: Path) -> None:
    selector = _load_selector()
    repository = _synthetic_repository(tmp_path)

    assert selector.select_targets(repository, [".github/workflows/ci.yml"]) == (
        "tests/repo/test_actions_parallel_workflows.py",
    )
    assert selector.select_targets(repository, ["docs/adr/0024-example.md"]) == (
        "tests/repo/test_b6_integration_contract.py",
        "tests/repo/test_site_repository_contract.py",
    )
    assert selector.select_targets(repository, ["CHANGELOG.md"]) == ("tests/repo/test_changelog_ci_contract.py",)
    assert selector.select_targets(repository, ["changelog.d/4526-example.fixed.md"]) == (
        "tests/commands/system/test_changelog_compile.py",
        "tests/repo/test_changelog_ci_contract.py",
    )
    assert selector.select_targets(repository, ["changelog.d/notes.txt"]) is None
    assert selector.select_targets(repository, ["tests/repo/test_actions_parallel_workflows.py"]) == (
        "tests/repo/test_actions_parallel_workflows.py",
    )


@pytest.mark.parametrize(
    "changed_paths",
    [
        ["unknown/file.txt"],
        ["/absolute/path.py"],
        ["../outside.py"],
        ["src\\youtube_automation\\core\\leaf.py"],
        ["tests/deleted_test.py"],
        ["tests/deleted_test.py", "tests/test_direct.py"],
        [".github/workflows/deleted.yml"],
        ["docs/adr/deleted.md"],
    ],
)
def test_unknown_unsafe_deleted_and_rename_like_inputs_fail_safe(tmp_path: Path, changed_paths: list[str]) -> None:
    selector = _load_selector()
    repository = _synthetic_repository(tmp_path)

    assert selector.select_targets(repository, changed_paths) is None


def test_parse_failure_fails_safe_instead_of_returning_partial_plan(tmp_path: Path) -> None:
    selector = _load_selector()
    repository = _synthetic_repository(tmp_path)
    _write(repository, "src/youtube_automation/core/broken.py", "def broken(:\n")

    assert selector.select_targets(repository, ["src/youtube_automation/core/leaf.py"]) is None


def _run_cli(changes: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments, str(changes)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_empty_input_prints_exact_all_and_json_has_same_plan(tmp_path: Path) -> None:
    changes = tmp_path / "changes.txt"
    changes.write_text("", encoding="utf-8")

    text_result = _run_cli(changes)
    json_result = _run_cli(changes, "--format", "json")

    assert text_result.returncode == 0
    assert text_result.stdout == "ALL\n"
    assert text_result.stderr == ""
    assert json_result.returncode == 0
    assert json.loads(json_result.stdout) == {"mode": "all", "targets": []}


def test_cli_output_is_deterministic_unique_and_existing_subset(tmp_path: Path) -> None:
    changes = tmp_path / "changes.txt"
    changes.write_text(
        "src/youtube_automation/configuration/channel_target.py\n"
        "src/youtube_automation/configuration/channel_target.py\n",
        encoding="utf-8",
    )

    # CLI も この test 自身も実ツリーを走査する。lane 契約の relocation probe が
    # `tests/` の実ファイルを動かす窓と重なると、selector は設計どおり `ALL` へ
    # fail-safe するため決定性の契約が成立しない。観測はすべて read lock の内側で
    # 済ませ、判定だけ外に出す。
    with shared_tests_tree_lock():
        first = _run_cli(changes)
        second = _run_cli(changes)
        json_result = _run_cli(changes, "--format", "json")
        targets = first.stdout.splitlines()
        all_tests = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in (REPO_ROOT / "tests").rglob("*.py")
            if path.name.startswith("test_") or path.name.endswith("_test.py")
        }
        targets_exist = all((REPO_ROOT / target).is_file() for target in targets)

    assert first.returncode == second.returncode == json_result.returncode == 0
    assert first.stdout == second.stdout
    assert targets == sorted(set(targets))
    assert targets
    assert set(targets) <= all_tests
    assert targets_exist
    assert json.loads(json_result.stdout) == {"mode": "selected", "targets": targets}


def test_cli_missing_argument_is_usage_error() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage:" in result.stderr
