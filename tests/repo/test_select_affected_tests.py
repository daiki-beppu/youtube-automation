from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Final

import pytest

from tests.helpers.paths import REPO_ROOT
from tests.helpers.tests_tree import shared_tests_tree_lock

SCRIPT = REPO_ROOT / ".github/scripts/select-affected-tests.py"
_GITHUB_ASSET_DIRECTORIES: Final = (".github/workflows", ".github/scripts")
_NON_TEST_PREFIXES: Final = ("tests/helpers/", "tests/fixtures/")


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
    _write(
        repository,
        "tests/test_dynamic_literal.py",
        "import importlib\n\nMODULE = importlib.import_module('youtube_automation.core.leaf')\n",
    )
    _write(
        repository,
        "tests/test_dynamic_wildcard.py",
        "import importlib\n\n\ndef _load(name):\n    return importlib.import_module(name)\n",
    )
    # 対応表の対象が1件でも実在しないと selector は ALL へ fail-safe する。
    # ここは期待値ではなく前提条件なので、対応表から機械的に用意する。
    selector = _load_selector()
    for pattern, targets in selector.PATH_TEST_MAP:
        if not pattern.endswith("/"):
            _write(repository, pattern)
        for target in targets:
            _write(repository, target)
    for target in selector.CHANGELOG_FRAGMENT_TESTS:
        _write(repository, target)
    _write(repository, "docs/adr/0024-example.md")
    _write(repository, "changelog.d/4526-example.fixed.md")
    _write(repository, "changelog.d/notes.txt")
    _write(repository, "some/other/changelog.d/4526-example.fixed.md")
    return repository


def test_source_change_selects_only_direct_and_transitive_importers(tmp_path: Path) -> None:
    selector = _load_selector()
    repository = _synthetic_repository(tmp_path)

    result = selector.select_targets(repository, ["src/youtube_automation/core/leaf.py"])

    assert result == (
        "tests/core/test_leaf.py",
        "tests/core/test_middle.py",
        "tests/test_direct.py",
        "tests/test_dynamic_literal.py",
        "tests/test_dynamic_wildcard.py",
    )


def test_literal_dynamic_import_is_resolved_as_a_static_dependency(tmp_path: Path) -> None:
    selector = _load_selector()
    repository = _synthetic_repository(tmp_path)

    result = selector.select_targets(repository, ["src/youtube_automation/other.py"])

    # other.py を静的 import する test_other に加え、リテラルでない動的 import を持つ
    # wildcard importer だけが追加される（leaf 系のリテラル動的 import は選ばれない）
    assert result == (
        "tests/test_dynamic_wildcard.py",
        "tests/test_other.py",
    )


def test_source_side_wildcard_is_a_bfs_root_for_its_transitive_importers(tmp_path: Path) -> None:
    selector = _load_selector()
    repository = _synthetic_repository(tmp_path)
    _write(
        repository,
        "src/youtube_automation/core/dynamic.py",
        "import importlib\n\n\ndef load(name):\n    return importlib.import_module(name)\n",
    )
    _write(
        repository,
        "src/youtube_automation/core/consumer.py",
        "from youtube_automation.core.dynamic import load\n",
    )
    _write(
        repository,
        "tests/test_consumer.py",
        "from youtube_automation.core.consumer import load\n",
    )

    result = selector.select_targets(repository, ["src/youtube_automation/other.py"])

    # source 側 wildcard（core.dynamic）は BFS 起点にも入るため、それを静的 import する
    # consumer 経由の test まで、無関係な source 変更でも保守的に選定される
    assert result == (
        "tests/test_consumer.py",
        "tests/test_dynamic_wildcard.py",
        "tests/test_other.py",
    )


def test_keyword_argument_dynamic_imports_are_resolved_or_treated_as_wildcards(tmp_path: Path) -> None:
    selector = _load_selector()
    repository = _synthetic_repository(tmp_path)
    _write(
        repository,
        "tests/test_keyword_literal.py",
        "import importlib\n\nMODULE = importlib.import_module(name='youtube_automation.core.leaf')\n",
    )
    _write(
        repository,
        "tests/test_keyword_wildcard.py",
        "import importlib\n\n\ndef _load(**kwargs):\n    return importlib.import_module(**kwargs)\n",
    )

    leaf_result = selector.select_targets(repository, ["src/youtube_automation/core/leaf.py"])
    other_result = selector.select_targets(repository, ["src/youtube_automation/other.py"])

    # キーワード引数のリテラルは静的依存として解決し、引数を特定できない呼び出しは wildcard 扱いにする
    assert "tests/test_keyword_literal.py" in leaf_result
    assert "tests/test_keyword_literal.py" not in other_result
    assert "tests/test_keyword_wildcard.py" in leaf_result
    assert "tests/test_keyword_wildcard.py" in other_result


def test_aliased_dynamic_imports_are_detected(tmp_path: Path) -> None:
    selector = _load_selector()
    repository = _synthetic_repository(tmp_path)
    _write(
        repository,
        "tests/test_alias_literal.py",
        "import importlib as il\n\nMODULE = il.import_module('youtube_automation.core.leaf')\n",
    )
    _write(
        repository,
        "tests/test_alias_wildcard.py",
        "from importlib import import_module as im\n\n\ndef _load(name):\n    return im(name)\n",
    )

    leaf_result = selector.select_targets(repository, ["src/youtube_automation/core/leaf.py"])
    other_result = selector.select_targets(repository, ["src/youtube_automation/other.py"])

    assert "tests/test_alias_literal.py" in leaf_result
    assert "tests/test_alias_literal.py" not in other_result
    assert "tests/test_alias_wildcard.py" in leaf_result
    assert "tests/test_alias_wildcard.py" in other_result


def test_non_source_changes_do_not_select_dynamic_wildcard_importers(tmp_path: Path) -> None:
    selector = _load_selector()
    repository = _synthetic_repository(tmp_path)

    assert selector.select_targets(repository, ["tests/core/test_leaf.py"]) == ("tests/core/test_leaf.py",)
    assert selector.select_targets(repository, ["changelog.d/4526-example.fixed.md"]) == (
        "tests/commands/system/test_changelog_compile.py",
        "tests/repo/test_changelog_ci_contract.py",
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

    # ci.yml は prefix エントリと完全一致エントリの両方にマッチし、両者が合成される
    assert selector.select_targets(repository, [".github/workflows/ci.yml"]) == (
        "tests/repo/test_actions_parallel_workflows.py",
        "tests/repo/test_changelog_ci_contract.py",
        "tests/repo/test_evals_workflow.py",
        "tests/repo/test_github_actions_pinning.py",
        "tests/repo/test_pyscn_diff_gate_contract.py",
        "tests/repo/test_pytest_lane_contract.py",
        "tests/repo/test_release_notes_contract.py",
        "tests/repo/test_select_affected_tests.py",
        "tests/repo/test_skill_catalog_removal.py",
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
    assert selector.select_targets(repository, ["some/other/changelog.d/4526-example.fixed.md"]) is None
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


def test_configuration_change_selects_the_reorganization_contract_test(tmp_path: Path) -> None:
    # #4438 の再発防止: configuration の公開 surface を importlib.import_module で
    # 検証する契約テストが、src/youtube_automation/configuration/ の変更で選ばれること
    selector = _load_selector()
    changed = ["src/youtube_automation/configuration/__init__.py"]

    with shared_tests_tree_lock():
        result = selector.select_targets(REPO_ROOT, changed)

    assert result is not None
    assert "tests/contracts/architecture/test_repository_reorganization_contract.py" in result


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


def _github_assets() -> list[str]:
    """`.github/workflows/` と `.github/scripts/` の実在ファイルを repo 相対 path で返す。"""
    return sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for directory in _GITHUB_ASSET_DIRECTORIES
        for path in (REPO_ROOT / directory).iterdir()
        if path.is_file()
    )


def _tests_referencing(basename: str) -> set[str]:
    """basename を path 成分として参照する test module を実ツリーから集める。

    期待値を PATH_TEST_MAP から導かないのは、対応表が間違っていても通る自己言及
    テストになるため。直前が path 区切り相当であることを要求し、`extensions.yml`
    が `release-extensions.yml` の一部へ誤マッチするのを防ぐ。
    """
    pattern = re.compile(r"(?<![A-Za-z0-9_.\-])" + re.escape(basename))
    referencing: set[str] = set()
    for path in (REPO_ROOT / "tests").rglob("*.py"):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if not (path.name.startswith("test_") or path.name.endswith("_test.py")):
            continue
        if relative.startswith(_NON_TEST_PREFIXES):
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            referencing.add(relative)
    return referencing


@pytest.mark.parametrize(
    "entries",
    [
        pytest.param(
            (
                (".github/workflows/", ("tests/core/test_leaf.py",)),
                (".github/workflows/ci.yml", ("tests/core/test_middle.py",)),
            ),
            id="prefix-first",
        ),
        pytest.param(
            (
                (".github/workflows/ci.yml", ("tests/core/test_middle.py",)),
                (".github/workflows/", ("tests/core/test_leaf.py",)),
            ),
            id="exact-first",
        ),
    ],
)
def test_every_matching_entry_contributes_regardless_of_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entries: tuple[tuple[str, tuple[str, ...]], ...],
) -> None:
    # #4658: 最初のマッチで打ち切ると prefix と完全一致のどちらか片方しか効かない。
    # エントリの並び順に依存せず、マッチした全エントリが合成されることを固定する。
    selector = _load_selector()
    repository = _synthetic_repository(tmp_path)
    monkeypatch.setattr(selector, "PATH_TEST_MAP", entries)

    assert selector.select_targets(repository, [".github/workflows/ci.yml"]) == (
        "tests/core/test_leaf.py",
        "tests/core/test_middle.py",
    )


@pytest.mark.parametrize("workflow", sorted(path.name for path in (REPO_ROOT / ".github/workflows").glob("*.yml")))
def test_every_workflow_change_selects_the_actions_pinning_gate(workflow: str) -> None:
    # test_github_actions_pinning.py は全 workflow を parametrize する supply-chain
    # ゲート。workflow 固有ではないため prefix 側で必ず選ばれる必要がある。
    selector = _load_selector()

    with shared_tests_tree_lock():
        result = selector.select_targets(REPO_ROOT, [f".github/workflows/{workflow}"])

    assert result is not None
    assert "tests/repo/test_github_actions_pinning.py" in result


def test_ci_yml_alone_selects_the_changelog_gate_contract() -> None:
    # #4658 の再発防止: ci.yml 単独変更で changelog ゲートの契約テストが選ばれること。
    selector = _load_selector()

    with shared_tests_tree_lock():
        result = selector.select_targets(REPO_ROOT, [".github/workflows/ci.yml"])

    assert result is not None
    assert "tests/repo/test_changelog_ci_contract.py" in result


@pytest.mark.parametrize("asset", _github_assets())
def test_github_asset_change_selects_every_test_that_references_it(asset: str) -> None:
    # 対応表のドリフト検出。実ツリーから参照元を導出し、選定結果が覆うことを要求する。
    selector = _load_selector()

    with shared_tests_tree_lock():
        result = selector.select_targets(REPO_ROOT, [asset])
        referencing = _tests_referencing(PurePosixPath(asset).name)

    if result is None:
        # ALL は全件実行なので契約は満たす。意図せず fail-safe へ落ちる path が
        # 増えていないことだけ固定する。
        assert asset in selector.FAIL_SAFE_EXACT
        return
    assert referencing <= set(result), f"{asset}: 対応表に載っていない参照元 test がある"


@pytest.mark.parametrize("asset", [".github/workflows/ci.yml", ".github/scripts/pyscn-diff-gate.py"])
def test_github_asset_change_selects_this_completeness_guard(asset: str) -> None:
    # ドリフト検出窓を PR 時点へ入れるため、対象ドメインを変更した PR では
    # 完全性契約テストを持つこの module 自身が選定される必要がある。
    selector = _load_selector()

    with shared_tests_tree_lock():
        result = selector.select_targets(REPO_ROOT, [asset])

    assert result is not None
    assert "tests/repo/test_select_affected_tests.py" in result


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        (".github/scripts/pyscn-diff-gate.py", "tests/repo/test_pyscn_diff_gate_contract.py"),
        (".github/scripts/run-affected-tests.py", "tests/repo/test_pytest_lane_contract.py"),
        (".github/scripts/any-usage-gate.sh", "tests/repo/test_any_usage_gate.py"),
        (".github/scripts/validate-changelog-fragments.py", "tests/repo/test_changelog_ci_contract.py"),
    ],
)
def test_github_scripts_change_is_narrowed_from_the_all_fail_safe(script: str, expected: str) -> None:
    # 未対応 path として ALL へ落ちていた経路を、対応する契約テストへ絞り込む。
    selector = _load_selector()

    with shared_tests_tree_lock():
        result = selector.select_targets(REPO_ROOT, [script])

    assert result is not None, f"{script}: ALL へ fail-safe している"
    assert expected in result


def test_selector_script_itself_still_fails_safe_to_all() -> None:
    # `.github/scripts/` の絞り込みが FAIL_SAFE_EXACT を上書きしないこと。
    selector = _load_selector()

    with shared_tests_tree_lock():
        result = selector.select_targets(REPO_ROOT, [".github/scripts/select-affected-tests.py"])

    assert result is None
