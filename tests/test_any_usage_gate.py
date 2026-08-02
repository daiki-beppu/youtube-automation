"""`.github/scripts/any-usage-gate.sh` の diff 基準点解決の契約.

このゲートは `ci_verify` が push 前に CI を再現する 4 ゲートの 1 つだが、基準点を
`origin/main` だけで解決していたため、remote を持たない隔離クローン（takt）では
常に self-skip して一度も判定していなかった（#3048）。基準点の解決順そのものを
テストで固定する。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.helpers.paths import REPO_ROOT

_REPO_ROOT = REPO_ROOT
_GATE_SCRIPT = _REPO_ROOT / ".github/scripts/any-usage-gate.sh"

# 実行環境の git 設定（既定ブランチ名・署名・hooksPath）に結果が左右されないよう、
# ユーザー / システム設定を遮断したうえで一時リポジトリを組み立てる。
_GIT_ENVIRONMENT = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "any-usage-gate-test",
    "GIT_AUTHOR_EMAIL": "any-usage-gate-test@example.invalid",
    "GIT_COMMITTER_NAME": "any-usage-gate-test",
    "GIT_COMMITTER_EMAIL": "any-usage-gate-test@example.invalid",
}

_BASE_SOURCE = """def handle(payload: str) -> None:
    return None
"""

# 追加行の 8 行目に Any 参照がある。違反行として報告されるのは import 行ではなく
# 実際に参照している行（`any_usage_python_resolver.py` が AST で解決する）。
_ANY_SOURCE = """from typing import Any


def handle(payload: str) -> None:
    return None


def handle_any(payload: Any) -> None:
    return None
"""
_ANY_VIOLATION = "module.py:8"

_CLEAN_SOURCE = """def handle(payload: str) -> None:
    return None


def handle_str(payload: str) -> None:
    return None
"""


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        env=os.environ | _GIT_ENVIRONMENT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _build_repository(tmp_path: Path, head_source: str) -> tuple[Path, str, str]:
    """base コミットと head コミットだけを持つリポジトリを作る。

    HEAD は `work` ブランチへ置き、`main` / `origin/main` は各テストが必要な分だけ
    作る（`git init -b work` により既定では `main` が存在しない）。
    """
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q", "-b", "work")

    (repository / "module.py").write_text(_BASE_SOURCE, encoding="utf-8")
    _git(repository, "add", "module.py")
    _git(repository, "commit", "-q", "-m", "base")
    base_sha = _git(repository, "rev-parse", "HEAD")

    (repository / "module.py").write_text(head_source, encoding="utf-8")
    _git(repository, "add", "module.py")
    _git(repository, "commit", "-q", "-m", "head")
    head_sha = _git(repository, "rev-parse", "HEAD")

    return repository, base_sha, head_sha


def _run_gate(repository: Path, **environment_overrides: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ | _GIT_ENVIRONMENT
    # 呼び出し元（CI の any-gate ジョブなど）の値を持ち込むと ref 解決を検証できない。
    environment.pop("PRE_PUSH_DIFF_BASE", None)
    environment |= environment_overrides

    return subprocess.run(
        ["bash", str(_GATE_SCRIPT)],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_uses_origin_main_when_it_is_available(tmp_path: Path) -> None:
    # origin/main を base に、ローカル main を HEAD と同一に置く。main を見ていれば
    # 差分が空になり素通りするため、検出できたことが origin/main 採用の証拠になる。
    repository, base_sha, head_sha = _build_repository(tmp_path, _ANY_SOURCE)
    _git(repository, "branch", "main", head_sha)
    _git(repository, "update-ref", "refs/remotes/origin/main", base_sha)

    result = _run_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert _ANY_VIOLATION in result.stderr


def test_falls_back_to_local_main_without_skipping(tmp_path: Path) -> None:
    # remote を持たない隔離クローン（takt）の形。差分に Any が無いので exit 0 だが、
    # skip した結果の 0 ではないことをスキップメッセージの不在で担保する。
    repository, base_sha, _ = _build_repository(tmp_path, _CLEAN_SOURCE)
    _git(repository, "branch", "main", base_sha)

    result = _run_gate(repository)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "スキップします" not in result.stderr


def test_detects_new_any_through_the_local_main_fallback(tmp_path: Path) -> None:
    repository, base_sha, _ = _build_repository(tmp_path, _ANY_SOURCE)
    _git(repository, "branch", "main", base_sha)

    result = _run_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert _ANY_VIOLATION in result.stderr


def test_skip_message_lists_every_tried_ref_when_none_resolves(tmp_path: Path) -> None:
    # base ref が 1 つも無いときだけスキップする。どの ref を試したのかが読み手に
    # 判らないと、素通りしている事実に気付けない。
    repository, _, _ = _build_repository(tmp_path, _ANY_SOURCE)

    result = _run_gate(repository)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "origin/main main" in result.stderr


def test_pre_push_diff_base_takes_precedence_over_ref_resolution(tmp_path: Path) -> None:
    # origin/main も main も HEAD と同一（差分なし）に置き、PRE_PUSH_DIFF_BASE だけ
    # が base を指す。検出できれば環境変数が ref 解決より優先されたことになる。
    repository, base_sha, head_sha = _build_repository(tmp_path, _ANY_SOURCE)
    _git(repository, "branch", "main", head_sha)
    _git(repository, "update-ref", "refs/remotes/origin/main", head_sha)

    result = _run_gate(repository, PRE_PUSH_DIFF_BASE=base_sha)

    assert result.returncode == 1, result.stdout + result.stderr
    assert _ANY_VIOLATION in result.stderr
