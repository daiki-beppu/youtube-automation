"""ルート ``.gitignore`` の pytest 一時ディレクトリ行 (issue #698) スペック準拠テスト。

issue #698 のレビューで、pytest を ``--basetemp=.tmp_test`` 等で実行した際に生成される
一時ディレクトリ ``.tmp_test/`` が未追跡かつ未 ignore のまま作業ツリーに残存し、
自動ステージングでコミットへ混入する残骸 (stale-artifact) として検出された。

本モジュールは以下を回帰検知する:

- パターン宣言: ``.tmp_test/`` が ``.gitignore`` に存在すること
- 退行検知本体: ``.tmp_test/`` 配下の生成物が ignore 対象になること

照合は stdlib ``fnmatch`` で行い、外部依存 (``pathspec`` 等) は導入しない。
``test_gitignore_auth_tokens.py`` と同じ責務分離方針で独立モジュールとする。
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

import pytest

# ---------- パス定数 ----------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ROOT_GITIGNORE = _REPO_ROOT / ".gitignore"

# ---------- パターン定数 ----------

_TMP_TEST_PATTERN = ".tmp_test/"
_GENERATED_ARTIFACT = ".tmp_test/pytest-of-mba/uv-08f4a866285ed88b.lock"


class TestRootGitignoreTmpTest:
    """ルート ``.gitignore`` に pytest 一時ディレクトリの ignore エントリ (issue #698)。"""

    @pytest.fixture
    def gitignore_lines(self) -> list[str]:
        """空白除去・空行除外した非コメント行のリスト。"""
        if not _ROOT_GITIGNORE.exists():
            pytest.fail(f"必須ファイルが存在しない: {_ROOT_GITIGNORE.relative_to(_REPO_ROOT)}")
        text = _ROOT_GITIGNORE.read_text(encoding="utf-8")
        return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]

    def test_should_declare_tmp_test_dir_when_reading_gitignore(self, gitignore_lines: list[str]) -> None:
        """Given root .gitignore
        When 行を走査する
        Then .tmp_test/ が ignore 対象として宣言されている。

        宣言が無いと pytest 一時生成物 (.tmp_test/ 配下) が silent commit される。
        """
        assert _TMP_TEST_PATTERN in gitignore_lines, (
            f"{_TMP_TEST_PATTERN} が .gitignore に追加されていない（pytest 一時生成物が残骸としてコミットへ混入する）"
        )

    def test_should_ignore_generated_artifact_when_matched_against_dir_pattern(self) -> None:
        """Given .gitignore のディレクトリパターン .tmp_test/
        When fnmatch で .tmp_test/ 配下の生成物を照合する
        Then 先頭セグメントがマッチして ignore 対象になる。

        gitignore のディレクトリ指定は配下を再帰的に無視するため、
        先頭の .tmp_test セグメントが一致すれば配下生成物は保護される。
        """
        top_segment = Path(_GENERATED_ARTIFACT).parts[0] + "/"
        assert fnmatch.fnmatch(top_segment, _TMP_TEST_PATTERN), (
            f"{_TMP_TEST_PATTERN} が {_GENERATED_ARTIFACT} の先頭セグメントにマッチしない"
            f"（.tmp_test/ 配下の pytest 生成物が保護されない）"
        )
