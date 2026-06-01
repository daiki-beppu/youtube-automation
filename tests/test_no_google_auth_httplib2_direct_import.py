"""`google_auth_httplib2` の直 import 0 件を機械的に維持する回帰テスト.

PyPI `google-auth-httplib2 0.4.0` (2026-05-07) で deprecated 表明されたため、
`docs/migration/google-auth-httplib2.md` と CLAUDE.md「依存ポリシー」節に基づき、
`src/youtube_automation/` 配下に `google_auth_httplib2` の直 import を新規追加しない。

`googleapiclient.discovery.build(..., credentials=...)` 経由の transitive 依存は
上流が non-httplib2 transport をサポートするまで残置する (移行計画書 Step 2)。
本テストは「直 import」のみを禁止し、transitive 依存への影響は与えない。

関連 issue: #475 / 親 #408 / 監査 R-04
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src" / "youtube_automation"

_FORBIDDEN_MODULE = "google_auth_httplib2"


def _iter_python_files() -> list[Path]:
    """`src/youtube_automation/` 配下の `.py` ファイルを列挙する."""
    return sorted(SRC_DIR.rglob("*.py"))


def _direct_imports(path: Path) -> list[tuple[int, str]]:
    """`path` の `.py` から `google_auth_httplib2` への直 import を抽出する.

    Returns:
        `(行番号, 該当 import 表現)` のリスト。空なら 0 件。
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root == _FORBIDDEN_MODULE:
                    hits.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            if root == _FORBIDDEN_MODULE:
                names = ", ".join(alias.name for alias in node.names)
                hits.append((node.lineno, f"from {module} import {names}"))
    return hits


def test_src_has_no_direct_google_auth_httplib2_import() -> None:
    """`src/youtube_automation/` 配下に `google_auth_httplib2` の直 import が無いこと.

    違反を検出した場合は (1) `googleapiclient.discovery.build(..., credentials=...)`
    経由の transitive 依存への切替、または (2) `docs/migration/google-auth-httplib2.md`
    の移行計画 Step 2 への明示的合流を検討すること。
    """
    violations: list[tuple[Path, int, str]] = []
    for path in _iter_python_files():
        for lineno, expression in _direct_imports(path):
            violations.append((path, lineno, expression))

    if violations:
        rendered = "\n".join(
            f"  {path.relative_to(REPO_ROOT)}:{lineno}: {expression}" for path, lineno, expression in violations
        )
        pytest.fail(
            "src/youtube_automation/ 配下で google_auth_httplib2 の直 import を検出しました。\n"
            "CLAUDE.md「依存ポリシー: deprecated 表明済み依存の取り扱い」および\n"
            "docs/migration/google-auth-httplib2.md を参照してください。\n"
            f"検出箇所:\n{rendered}"
        )


def test_regression_test_scans_actual_source_tree() -> None:
    """テストが実在する `src/` を走査していることを保証する (空走査の防止)."""
    assert SRC_DIR.is_dir(), f"src/ が見つかりません: {SRC_DIR}"
    files = _iter_python_files()
    assert files, "src/youtube_automation/ 配下の .py が 0 件です (テスト自身の保護)"
