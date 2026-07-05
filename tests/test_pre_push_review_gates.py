"""review 頻出パターンを検出する pre-push gate の契約テスト。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LEFTHOOK_CONFIG_PATH = _REPO_ROOT / "lefthook.yml"
_DEVELOPMENT_DOC_PATH = _REPO_ROOT / "docs" / "development.md"
_CHANGELOG_GATE_PATH = _REPO_ROOT / ".lefthook" / "pre-push" / "changelog-gate.sh"
_TEST_DIFF_GATE_PATH = _REPO_ROOT / ".lefthook" / "pre-push" / "test-diff-gate.sh"
_ANY_USAGE_GATE_PATH = _REPO_ROOT / ".lefthook" / "pre-push" / "any-usage-gate.sh"
_ZERO_SHA = "0" * 40


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )


def _run_gate(
    repo: Path, script_path: Path, *, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(script_path)],
        cwd=repo,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def _run_gate_with_stdin(
    repo: Path, script_path: Path, stdin_text: str, *, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(script_path)],
        cwd=repo,
        input=stdin_text,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def _write(repo: Path, relative_path: str, text: str) -> None:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit_all(repo: Path, message: str) -> None:
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", message)


def _init_repo_with_origin_main(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test User")
    _write(repo, "README.md", "# test\n")
    _commit_all(repo, "base")
    _run_git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def test_lefthook_wires_single_stdin_entrypoint_chaining_all_pre_push_gates() -> None:
    """pre-push は changelog-gate のみが stdin を持ち、削除 push 判定を全ゲートへ連鎖適用する。

    lefthook は同一 hook で use_stdin を持てるコマンドを 1 つに制限するため、
    test-diff-gate / any-usage-gate を独立コマンドにすると削除 push 判定を
    共有できない（#1525 レビュー指摘）。changelog-gate.sh を唯一のエントリ
    ポイントにし、内部で他 2 ゲートを呼び出すことで解決する。
    """
    config = yaml.safe_load(_LEFTHOOK_CONFIG_PATH.read_text(encoding="utf-8"))
    commands = config["pre-push"]["commands"]

    assert set(commands.keys()) == {"changelog-gate"}
    assert commands["changelog-gate"]["use_stdin"] is True
    assert commands["changelog-gate"]["run"] == "bash .lefthook/pre-push/changelog-gate.sh"

    gate_script = _CHANGELOG_GATE_PATH.read_text(encoding="utf-8")
    assert "test-diff-gate.sh" in gate_script
    assert "any-usage-gate.sh" in gate_script


def test_changelog_gate_skips_all_gates_on_branch_deletion_push(tmp_path: Path) -> None:
    """削除 push は changelog / test-diff / any-usage のいずれも実行しない。"""
    repo = _init_repo_with_origin_main(tmp_path)
    _write(
        repo,
        "extensions/demo/lib/types.ts",
        "export const passthrough = (value: " + "any) => value;\n",
    )
    _commit_all(repo, "add broad ts type")
    current_sha = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
    stdin_text = f"refs/heads/feature {_ZERO_SHA} refs/heads/feature {current_sha}\n"

    result = _run_gate_with_stdin(repo, _CHANGELOG_GATE_PATH, stdin_text)

    assert result.returncode == 0
    assert "changelog-gate: ブランチ削除 push のためスキップします。" in result.stderr
    assert "any-usage-gate" not in result.stderr
    assert "test-diff-gate" not in result.stderr


def test_changelog_gate_chains_any_usage_gate_failure_on_normal_push(tmp_path: Path) -> None:
    """削除 push でない通常 push では any-usage-gate の違反が changelog-gate 経由でも検出される。"""
    repo = _init_repo_with_origin_main(tmp_path)
    _write(
        repo,
        "extensions/demo/lib/types.ts",
        "export const passthrough = (value: " + "any) => value;\n",
    )
    _commit_all(repo, "add broad ts type")
    current_sha = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
    stdin_text = f"refs/heads/feature {current_sha} refs/heads/feature {_ZERO_SHA}\n"

    result = _run_gate_with_stdin(repo, _CHANGELOG_GATE_PATH, stdin_text)

    assert result.returncode == 1
    assert "any-usage-gate: ERROR" in result.stderr


def test_test_diff_gate_warns_for_python_code_without_test_diff(tmp_path: Path) -> None:
    repo = _init_repo_with_origin_main(tmp_path)
    _write(repo, "src/youtube_automation/new_feature.py", "def main() -> str:\n    return 'ok'\n")
    _commit_all(repo, "change python code")

    result = _run_gate(repo, _TEST_DIFF_GATE_PATH)

    assert result.returncode == 0
    assert "WARNING: src/youtube_automation/ に差分がありますが tests/ の差分がありません。" in result.stderr
    assert "SKIP_TEST_DIFF=1 git push" in result.stderr


def test_test_diff_gate_warns_for_extension_lib_without_test_diff(tmp_path: Path) -> None:
    repo = _init_repo_with_origin_main(tmp_path)
    _write(repo, "extensions/demo/lib/types.ts", "export const mode = 'demo';\n")
    _commit_all(repo, "change extension lib")

    result = _run_gate(repo, _TEST_DIFF_GATE_PATH)

    assert result.returncode == 0
    assert (
        "WARNING: extensions/*/lib/ に差分がありますが extensions 配下の *.test.ts 差分がありません。" in result.stderr
    )
    assert "SKIP_TEST_DIFF=1 git push" in result.stderr


def test_test_diff_gate_records_explicit_skip(tmp_path: Path) -> None:
    repo = _init_repo_with_origin_main(tmp_path)

    result = _run_gate(repo, _TEST_DIFF_GATE_PATH, extra_env={"SKIP_TEST_DIFF": "1"})

    assert result.returncode == 0
    assert "test-diff-gate: SKIP_TEST_DIFF=1 のためスキップします。" in result.stderr


def test_test_diff_gate_no_warning_when_corresponding_tests_touched(tmp_path: Path) -> None:
    """src/tests・extension lib/test が対で変更されていれば警告しない（成功パス）。

    extensions/demo/lib/types.test.ts は extensions/*/lib/* にも *.test.ts にも
    該当するネストケース。case/esac の排他マッチだと lib 側だけが確定し
    テスト差分ゼロと誤警告する回帰がある（#1525 レビュー指摘）。
    """
    repo = _init_repo_with_origin_main(tmp_path)
    _write(repo, "src/youtube_automation/new_feature.py", "def main() -> str:\n    return 'ok'\n")
    _write(repo, "tests/test_new_feature.py", "def test_main() -> None:\n    assert True\n")
    _write(repo, "extensions/demo/lib/types.ts", "export const mode = 'demo';\n")
    _write(repo, "extensions/demo/lib/types.test.ts", "test('mode', () => {});\n")
    _commit_all(repo, "change code with matching tests")

    result = _run_gate(repo, _TEST_DIFF_GATE_PATH)

    assert result.returncode == 0
    assert "WARNING" not in result.stderr


def test_test_diff_gate_recognizes_test_file_nested_under_extension_lib(tmp_path: Path) -> None:
    """extensions/*/lib/*.test.ts 単独の変更でも test 差分として認識する。"""
    repo = _init_repo_with_origin_main(tmp_path)
    _write(repo, "extensions/demo/lib/types.ts", "export const mode = 'demo';\n")
    _write(repo, "extensions/demo/lib/types.test.ts", "test('mode', () => {});\n")
    _commit_all(repo, "change extension lib with nested test")

    result = _run_gate(repo, _TEST_DIFF_GATE_PATH)

    assert result.returncode == 0
    assert "WARNING" not in result.stderr


def test_any_usage_gate_fails_for_new_code_additions(tmp_path: Path) -> None:
    repo = _init_repo_with_origin_main(tmp_path)
    _write(
        repo,
        "extensions/demo/lib/types.ts",
        "export const passthrough = (value: " + "any) => value;\n",
    )
    _commit_all(repo, "add broad ts type")

    result = _run_gate(repo, _ANY_USAGE_GATE_PATH)

    assert result.returncode == 1
    assert "any-usage-gate: ERROR" in result.stderr
    assert "レビューポリシー" in result.stderr
    assert "REJECT" in result.stderr
    assert "extensions/demo/lib/types.ts:1" in result.stderr


def test_any_usage_gate_fails_for_new_python_typing_any_additions(tmp_path: Path) -> None:
    repo = _init_repo_with_origin_main(tmp_path)
    _write(
        repo,
        "src/youtube_automation/broad_type.py",
        "import typing\n\nvalue: typing." + "Any = None\n",
    )
    _commit_all(repo, "add broad python type")

    result = _run_gate(repo, _ANY_USAGE_GATE_PATH)

    assert result.returncode == 1
    assert "any-usage-gate: ERROR" in result.stderr
    assert "レビューポリシー" in result.stderr
    assert "REJECT" in result.stderr
    assert "src/youtube_automation/broad_type.py:3" in result.stderr


def test_any_usage_gate_ignores_existing_lines_at_origin_main(tmp_path: Path) -> None:
    repo = _init_repo_with_origin_main(tmp_path)
    _write(repo, "src/youtube_automation/existing.py", "value: typing." + "Any = None\n")
    _commit_all(repo, "base broad python type")
    _run_git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    result = _run_gate(repo, _ANY_USAGE_GATE_PATH)

    assert result.returncode == 0
    assert result.stderr == ""


def test_any_usage_gate_fails_for_python_file_outside_src_and_tests(tmp_path: Path) -> None:
    """スコープはディレクトリ非依存。.claude/skills/ 配下の参照スクリプトも対象。"""
    repo = _init_repo_with_origin_main(tmp_path)
    _write(
        repo,
        ".claude/skills/demo/references/helper.py",
        "import typing\n\nvalue: typing." + "Any = None\n",
    )
    _commit_all(repo, "add broad type to skill reference script")

    result = _run_gate(repo, _ANY_USAGE_GATE_PATH)

    assert result.returncode == 1
    assert ".claude/skills/demo/references/helper.py:3" in result.stderr


def test_any_usage_gate_fails_for_root_level_typescript_file(tmp_path: Path) -> None:
    """スコープはディレクトリ非依存。リポジトリ直下の *.ts も対象。"""
    repo = _init_repo_with_origin_main(tmp_path)
    _write(repo, "tool.config.ts", "export const passthrough = (value: " + "any) => value;\n")
    _commit_all(repo, "add broad type to root config")

    result = _run_gate(repo, _ANY_USAGE_GATE_PATH)

    assert result.returncode == 1
    assert "tool.config.ts:1" in result.stderr


def test_any_usage_gate_fails_for_direct_import_bare_any_usage(tmp_path: Path) -> None:
    """`from typing import Any` 経由の裸の Any も検出する（typing 修飾形だけでは不十分）。"""
    repo = _init_repo_with_origin_main(tmp_path)
    _write(
        repo,
        "src/youtube_automation/broad_type.py",
        "from typing import Any\n\nvalue: Any = None\n",
    )
    _commit_all(repo, "add direct import bare any")

    result = _run_gate(repo, _ANY_USAGE_GATE_PATH)

    assert result.returncode == 1
    assert "any-usage-gate: ERROR" in result.stderr
    assert "src/youtube_automation/broad_type.py:3" in result.stderr


def test_any_usage_gate_ignores_bare_any_word_without_direct_typing_import(tmp_path: Path) -> None:
    """typing の Any を import していないファイルの `Any` は無害な識別子として無視する。"""
    repo = _init_repo_with_origin_main(tmp_path)
    _write(
        repo,
        "src/youtube_automation/custom_type.py",
        "class Any:\n    pass\n",
    )
    _commit_all(repo, "add unrelated Any class")

    result = _run_gate(repo, _ANY_USAGE_GATE_PATH)

    assert result.returncode == 0
    assert result.stderr == ""


def test_development_docs_describe_review_gates_and_skip_contract() -> None:
    text = _DEVELOPMENT_DOC_PATH.read_text(encoding="utf-8")

    for token in (
        ".lefthook/pre-push/test-diff-gate.sh",
        ".lefthook/pre-push/any-usage-gate.sh",
        "SKIP_TEST_DIFF=1 git push",
        "typing module 経由の Any 型",
        "TypeScript の any 型注釈",
    ):
        assert token in text
