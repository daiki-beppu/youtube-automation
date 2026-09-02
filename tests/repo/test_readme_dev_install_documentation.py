"""docs/development.md の開発者向け節が Issue #329 完了条件 3 を満たすかを検証する。

Issue #329: pytest 全実行で optional dependency 未インストール時の collection error を解消

完了条件 3 が「どの optional dep が必要かを開発者向け文書に明文化」のため、
本リポジトリでは docs/development.md に以下を含めることで満たす:

1. Developer bootstrap のコマンド例から削除済み extra (`--extra veo`) を取り除き、
   正規 setup wrapper で依存が揃うことを示す。
   - 理由: `pyproject.toml` に `veo` extra が存在せず、
     `--extra veo` を案内し続けるのは「optional dep を明文化」の主旨と矛盾する。
   - Plan 024 (dev 依存一本化) で `pytest` / `ruff` は `[dependency-groups].dev`
     経由の default group となり、`--extra dev` 指定は不要になった。

2. テスト実行節に、`uv run pytest` が collection error 0 件で走るために
   何が揃っている必要があるかを明文化する。
   - 検索性のため Issue #329 で使われた語彙 (`collection error` / `optional dependency`)
     を 1 箇所以上含める。
   - 主因となった `Pillow` が main dependencies に含まれている事実を示す。
   - `pytest` 自体は `[dependency-groups].dev` 経由で入ることを示す。

参照: `.takt/runs/20260518-060411-issue-329-.../reports/plan.md`
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT

# リポジトリルート (tests/ の親)
_REPO_ROOT = REPO_ROOT
DEVELOPMENT_DOC = _REPO_ROOT / "docs" / "development.md"


# ---------- 共通ヘルパー ----------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _developer_bootstrap_section(text: str) -> str:
    """開発者 bootstrap 見出しから次の `## ` 見出し直前までを抽出する。"""
    match = re.search(
        r"^## 開発者 bootstrap（正規入口）.*?(?=^## |\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError("docs/development.md に開発者 bootstrap 節が見つかりません")
    return match.group(0)


def _developer_bootstrap_block(dev_section: str) -> str:
    """開発者 bootstrap 節の bash code block を抽出する。"""
    match = re.search(
        r"```bash\n(.*?)```",
        dev_section,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError("docs/development.md の開発者 bootstrap 節に bash code block が見つかりません")
    return match.group(1)


def _test_run_section(text: str) -> str:
    """テスト実行節を次の `## ` 見出し直前まで抽出する。"""
    match = re.search(
        r"^## テスト実行（pytest-xdist による並列化）(.*?)(?=^## |\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError("docs/development.md にテスト実行節が見つかりません")
    return match.group(1)


# ---------- 前提: 開発文書とセクションが存在する ----------


def test_development_doc_exists() -> None:
    """Given リポジトリルート
    When docs/development.md を探す
    Then ファイルが存在する。
    """
    assert DEVELOPMENT_DOC.exists(), f"{DEVELOPMENT_DOC} が存在しません"


def test_development_doc_has_bootstrap_section() -> None:
    """Given docs/development.md
    When 開発者 bootstrap 見出しを探す
    Then 節が存在する。
    """
    text = _read(DEVELOPMENT_DOC)
    assert "## 開発者 bootstrap（正規入口）" in text, "docs/development.md に開発者 bootstrap 節がない"


def test_developer_bootstrap_drops_removed_veo_extra() -> None:
    block = _developer_bootstrap_block(_developer_bootstrap_section(_read(DEVELOPMENT_DOC)))
    assert "--extra veo" not in block, f"Developer bootstrap に削除済み extra `--extra veo` が残存:\n{block}"


def test_developer_bootstrap_uses_canonical_devshell_entry() -> None:
    block = _developer_bootstrap_block(_developer_bootstrap_section(_read(DEVELOPMENT_DOC)))
    assert "nix develop" in block
    assert "uv sync" not in block
    assert "lefthook" not in block
    assert "--extra dev" not in block, (
        f"Developer bootstrap に不要な `--extra dev` が残存 (dev は default group):\n{block}"
    )


# ---------- テスト実行節: Issue #329 完了条件 3 の明文化 ----------


def test_test_run_section_mentions_collection_error_term() -> None:
    """Given docs/development.md のテスト実行節
    When 本文を読む
    Then Issue #329 で使われた `collection error` の語彙が含まれている。

    将来同じ症状で `collection error` を grep した開発者がたどり着けるようにするため。
    """
    section = _test_run_section(_read(DEVELOPMENT_DOC))
    assert "collection error" in section, (
        f"テスト実行節に `collection error` の語彙がない (Issue #329 検索性のため必須):\n{section}"
    )


def test_test_run_section_mentions_optional_dependency_term() -> None:
    """Given docs/development.md のテスト実行節
    When 本文を読む
    Then `optional dependency` (または日本語の "optional 依存") の語彙が含まれている。
    """
    section = _test_run_section(_read(DEVELOPMENT_DOC))
    assert ("optional dependency" in section) or ("optional 依存" in section.lower()), (
        f"テスト実行節に `optional dependency` の語彙がない:\n{section}"
    )


def test_test_run_section_mentions_pillow_in_main_deps() -> None:
    """Given docs/development.md のテスト実行節
    When 本文を読む
    Then Issue #329 の主因だった `Pillow` への言及がある。

    `Pillow` が main dependencies に含まれている事実 (issue 起票時点と現状の差) を
    開発者に伝えるため。
    """
    section = _test_run_section(_read(DEVELOPMENT_DOC))
    assert "Pillow" in section, f"テスト実行節に `Pillow` への言及がない (Issue #329 主因の dep):\n{section}"


def test_test_run_section_explains_uv_sync_is_sufficient() -> None:
    """Given docs/development.md のテスト実行節
    When 本文を読む
    Then `uv sync` 単独でテストが揃う旨が案内されている。
    """
    section = _test_run_section(_read(DEVELOPMENT_DOC))
    assert "uv sync" in section, f"テスト実行節に `uv sync` で揃う旨の案内がない:\n{section}"


def test_test_run_section_is_expanded_beyond_single_codeblock() -> None:
    """Given docs/development.md のテスト実行節
    When 本文の中身を計測する
    Then 単一の `uv run pytest` コードブロックだけでなく、説明文が追記されている。

    Issue #329 完了条件 3 を満たすには、コマンド例 1 行だけでは「optional dep の明文化」と
    呼べないため、少なくとも 1 行以上の説明文が追加されているはず。
    """
    section = _test_run_section(_read(DEVELOPMENT_DOC))
    # コードフェンス・空行・見出し以外の散文行を数える
    prose_lines = [
        ln.strip()
        for ln in section.splitlines()
        if ln.strip()
        and not ln.strip().startswith("```")
        and not ln.strip().startswith("#")
        and not ln.strip().startswith("uv ")  # コードブロック内の `uv run pytest` 等
    ]
    assert len(prose_lines) >= 2, (
        "テスト実行節が単一コードブロックのままで、説明文が追記されていない "
        f"(prose lines = {len(prose_lines)}):\n{section}"
    )


# ---------- 横断: dev install 説明と pyproject.toml の整合 ----------


def test_development_doc_does_not_advertise_empty_extras() -> None:
    text = _read(DEVELOPMENT_DOC)
    assert "--extra veo" not in text, "docs/development.md に削除済み `--extra veo` の案内が残存"


def test_pyproject_does_not_define_veo_extra() -> None:
    project = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    optional_dependencies = project.get("project", {}).get("optional-dependencies", {})
    assert "veo" not in optional_dependencies


@pytest.mark.parametrize(
    "package_name",
    ["Pillow", "pandas", "pyyaml"],
    ids=["Pillow", "pandas", "pyyaml"],
)
def test_main_dependency_listed_in_pyproject(package_name: str) -> None:
    pyproject = _REPO_ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    # `[project] dependencies = [ ... ]` ブロックを抽出
    match = re.search(
        r"^dependencies\s*=\s*\[(.*?)\]",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert match, "pyproject.toml に `dependencies = [...]` ブロックがない"
    deps_block = match.group(1)
    # 大小文字無視で部分一致を検査 (`Pillow` / `pillow` どちらでも許容)
    assert package_name.lower() in deps_block.lower(), (
        f"pyproject.toml の main dependencies に `{package_name}` がない:\n{deps_block}"
    )
