"""ルート ``.gitignore`` の auth token 行 (issue #158) スペック準拠テスト。

issue #158 で ``auth/token.json`` の exact 一致を ``auth/token*.json`` に glob 化する。
本モジュールは以下を回帰検知する:

- パターン宣言: ``auth/token*.json`` が ``.gitignore`` に存在すること
- バグ修正本体: ``auth/token_streaming.json`` が ignore 対象になること
- 後方互換: 旧来の ``auth/token.json`` も引き続き ignore 対象であること
- 退行検知: 旧 exact 形式 ``auth/token.json`` が単独行として残っていないこと

照合は stdlib ``fnmatch`` で行い、外部依存 (``pathspec`` 等) は導入しない。
gitignore 固有構文 (``**`` / ``!`` / leading ``/``) は本パターンに含まれず ``fnmatch`` で十分。

責務分離のため ``tests/test_terraform_streaming.py::TestRootGitignoreTerraformEntries``
には混ぜず、本ファイルを独立モジュールとして分離する。
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

import pytest

# ---------- パス定数 ----------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ROOT_GITIGNORE = _REPO_ROOT / ".gitignore"

# ---------- パターン定数 ----------

_GLOB_PATTERN = "auth/token*.json"
_LEGACY_EXACT = "auth/token.json"
_BACKWARD_COMPAT_NAME = "auth/token.json"
_REGRESSION_TARGET_NAME = "auth/token_streaming.json"


class TestRootGitignoreAuthTokens:
    """ルート ``.gitignore`` に auth token の glob ignore エントリ (issue #158)。"""

    @pytest.fixture
    def gitignore_lines(self) -> list[str]:
        """空白除去・空行除外した非コメント行のリスト。"""
        if not _ROOT_GITIGNORE.exists():
            pytest.fail(f"必須ファイルが存在しない: {_ROOT_GITIGNORE.relative_to(_REPO_ROOT)}")
        text = _ROOT_GITIGNORE.read_text(encoding="utf-8")
        return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]

    def test_should_declare_auth_token_glob_pattern_when_reading_gitignore(self, gitignore_lines: list[str]) -> None:
        """Given root .gitignore
        When 行を走査する
        Then auth/token*.json が ignore 対象として宣言されている。

        宣言が無いと streaming token (auth/token_streaming.json) が silent commit される。
        """
        assert _GLOB_PATTERN in gitignore_lines, (
            f"{_GLOB_PATTERN} が .gitignore に追加されていない（auth/token_streaming.json が silent commit される）"
        )

    def test_should_ignore_streaming_token_when_matched_against_glob(self) -> None:
        """Given .gitignore の glob パターン auth/token*.json
        When fnmatch で auth/token_streaming.json を照合する
        Then マッチして ignore 対象になる。

        issue #158 のバグ修正本体: 旧 exact 形式では streaming token が保護されない。
        """
        assert fnmatch.fnmatch(_REGRESSION_TARGET_NAME, _GLOB_PATTERN), (
            f"{_GLOB_PATTERN} が {_REGRESSION_TARGET_NAME} にマッチしない"
            f"（issue #158 のバグ修正が機能しておらず streaming token が保護されない）"
        )

    def test_should_keep_ignoring_legacy_token_when_matched_against_glob(self) -> None:
        """Given .gitignore の glob パターン auth/token*.json
        When fnmatch で auth/token.json を照合する
        Then マッチして ignore 対象になる。

        後方互換性: glob は旧 exact パターンの strict superset である必要がある。
        崩れると既存運用 (auth/token.json) が破壊される。
        """
        assert fnmatch.fnmatch(_BACKWARD_COMPAT_NAME, _GLOB_PATTERN), (
            f"{_GLOB_PATTERN} が {_BACKWARD_COMPAT_NAME} にマッチしない"
            f"（旧 exact パターンの後方互換が崩れ、既存運用が破壊される）"
        )

    def test_should_not_retain_bare_legacy_token_line_when_glob_is_in_place(self, gitignore_lines: list[str]) -> None:
        """Given root .gitignore
        When 行を走査する
        Then 旧 exact 形式 auth/token.json が単独行として残っていない。

        glob (auth/token*.json) と exact (auth/token.json) の併記は冗長で意図不明瞭。
        glob 化の意義 (将来 token_*.json 自動カバー) も読み取りにくくなる。
        """
        assert _LEGACY_EXACT not in gitignore_lines, (
            f"旧 exact 形式 {_LEGACY_EXACT} が .gitignore に単独行で残存している"
            f"（{_GLOB_PATTERN} と冗長で、glob 化の意図が不明瞭になる）"
        )
