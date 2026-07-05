"""review 頻出パターンを検出する pre-push gate の契約テスト。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LEFTHOOK_CONFIG_PATH = _REPO_ROOT / "lefthook.yml"
_DEVELOPMENT_DOC_PATH = _REPO_ROOT / "docs" / "development.md"
_TEST_DIFF_GATE_PATH = _REPO_ROOT / ".lefthook" / "pre-push" / "test-diff-gate.sh"
_ANY_USAGE_GATE_PATH = _REPO_ROOT / ".lefthook" / "pre-push" / "any-usage-gate.sh"


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


def test_lefthook_wires_review_gates_without_consuming_pre_push_stdin() -> None:
    """追加 gate は stdin を読まず、削除 push 判定は changelog-gate だけが担う。"""
    config = yaml.safe_load(_LEFTHOOK_CONFIG_PATH.read_text(encoding="utf-8"))
    commands = config["pre-push"]["commands"]

    assert commands["changelog-gate"].get("use_stdin") is True
    assert commands["test-diff-gate"] == {"run": "bash .lefthook/pre-push/test-diff-gate.sh"}
    assert commands["any-usage-gate"] == {"run": "bash .lefthook/pre-push/any-usage-gate.sh"}
    assert [name for name, command in commands.items() if command.get("use_stdin") is True] == ["changelog-gate"]


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
