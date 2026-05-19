"""README の Development 節が Issue #329 完了条件 3 を満たすかを検証する。

Issue #329: pytest 全実行で optional dependency 未インストール時の collection error を解消

完了条件 3 が「どの optional dep が必要かを README/CONTRIBUTING に明文化」のため、
本リポジトリでは README.md の Development 節に以下を含めることで満たす:

1. Editable install のコマンド例から空 extra (`--extra veo`) を取り除き、
   `uv sync --extra dev` 単独で揃うことを示す。
   - 理由: `pyproject.toml:33-35` で `veo = []` (空 extra) になっており、
     `--extra veo` を案内し続けるのは「optional dep を明文化」の主旨と矛盾する。

2. テスト実行節に、`uv run pytest` が collection error 0 件で走るために
   何が揃っている必要があるかを明文化する。
   - 検索性のため Issue #329 で使われた語彙 (`collection error` / `optional dependency`)
     を 1 箇所以上含める。
   - 主因となった `Pillow` が main dependencies に含まれている事実を示す。
   - `pytest` 自体は `[project.optional-dependencies].dev` 経由で入ることを示す。

参照: `.takt/runs/20260518-060411-issue-329-.../reports/plan.md`
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# リポジトリルート (tests/ の親)
_REPO_ROOT = Path(__file__).resolve().parent.parent
README = _REPO_ROOT / "README.md"


# ---------- 共通ヘルパー ----------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _development_section(text: str) -> str:
    """`## Development` 見出しから次の `## ` 見出し直前までを抽出する。"""
    match = re.search(
        r"^## Development\b.*?(?=^## |\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError("README.md に `## Development` 節が見つかりません")
    return match.group(0)


def _editable_install_block(dev_section: str) -> str:
    """Development 節内の Editable install 配下の最初の bash コードブロックを抽出する。"""
    match = re.search(
        r"### Editable install\b.*?```bash\n(.*?)```",
        dev_section,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError("README.md に Editable install の bash コードブロックが見つかりません")
    return match.group(1)


def _test_run_section(dev_section: str) -> str:
    """Development 節内の `### テスト実行` ブロックを抽出する (次の `### ` まで)。"""
    match = re.search(
        r"### テスト実行\b(.*?)(?=^### |\Z)",
        dev_section,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError("README.md に `### テスト実行` 節が見つかりません")
    return match.group(1)


# ---------- 前提: README とセクションが存在する ----------


def test_readme_file_exists() -> None:
    """Given リポジトリルート
    When README.md を探す
    Then ファイルが存在する。
    """
    assert README.exists(), f"{README} が存在しません"


def test_readme_has_development_section() -> None:
    """Given README.md
    When `## Development` を探す
    Then 節が存在する。
    """
    text = _read(README)
    assert "## Development" in text, "README.md に `## Development` 節がない"


# ---------- Editable install: `--extra veo` の撤去 ----------


def test_editable_install_drops_empty_veo_extra() -> None:
    """Given README.md Editable install ブロック
    When `uv sync` コマンドを読む
    Then 空 extra `--extra veo` が削除されている (pyproject.toml で `veo = []`)。
    """
    block = _editable_install_block(_development_section(_read(README)))
    assert "--extra veo" not in block, (
        f"Editable install に空 extra `--extra veo` が残存 (pyproject.toml で `veo = []` なので no-op):\n{block}"
    )


def test_editable_install_uses_uv_sync_extra_dev() -> None:
    """Given README.md Editable install ブロック
    When 推奨コマンドを読む
    Then `uv sync --extra dev` が案内されている。
    """
    block = _editable_install_block(_development_section(_read(README)))
    assert "uv sync --extra dev" in block, f"Editable install で `uv sync --extra dev` が案内されていない:\n{block}"


# ---------- テスト実行節: Issue #329 完了条件 3 の明文化 ----------


def test_test_run_section_mentions_collection_error_term() -> None:
    """Given README.md `### テスト実行` 節
    When 本文を読む
    Then Issue #329 で使われた `collection error` の語彙が含まれている。

    将来同じ症状で `collection error` を grep した開発者がたどり着けるようにするため。
    """
    section = _test_run_section(_development_section(_read(README)))
    assert "collection error" in section, (
        f"テスト実行節に `collection error` の語彙がない (Issue #329 検索性のため必須):\n{section}"
    )


def test_test_run_section_mentions_optional_dependency_term() -> None:
    """Given README.md `### テスト実行` 節
    When 本文を読む
    Then `optional dependency` (または日本語の "optional 依存") の語彙が含まれている。
    """
    section = _test_run_section(_development_section(_read(README)))
    assert ("optional dependency" in section) or ("optional 依存" in section.lower()), (
        f"テスト実行節に `optional dependency` の語彙がない:\n{section}"
    )


def test_test_run_section_mentions_pillow_in_main_deps() -> None:
    """Given README.md `### テスト実行` 節
    When 本文を読む
    Then Issue #329 の主因だった `Pillow` への言及がある。

    `Pillow` が main dependencies に含まれている事実 (issue 起票時点と現状の差) を
    開発者に伝えるため。
    """
    section = _test_run_section(_development_section(_read(README)))
    assert "Pillow" in section, f"テスト実行節に `Pillow` への言及がない (Issue #329 主因の dep):\n{section}"


def test_test_run_section_explains_extra_dev_is_sufficient() -> None:
    """Given README.md `### テスト実行` 節
    When 本文を読む
    Then `uv sync --extra dev` 単独でテストが揃う旨が案内されている。
    """
    section = _test_run_section(_development_section(_read(README)))
    assert "uv sync --extra dev" in section, f"テスト実行節に `uv sync --extra dev` で揃う旨の案内がない:\n{section}"


def test_test_run_section_is_expanded_beyond_single_codeblock() -> None:
    """Given README.md `### テスト実行` 節
    When 本文の中身を計測する
    Then 単一の `uv run pytest` コードブロックだけでなく、説明文が追記されている。

    Issue #329 完了条件 3 を満たすには、コマンド例 1 行だけでは「optional dep の明文化」と
    呼べないため、少なくとも 1 行以上の説明文が追加されているはず。
    """
    section = _test_run_section(_development_section(_read(README)))
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


def test_readme_does_not_advertise_empty_extras() -> None:
    """Given README.md 全体
    When `--extra veo` の登場箇所を探す
    Then 一切登場しない (pyproject.toml で `veo = []` の空 extra のため)。

    Editable install ブロック以外の場所にも残っていないかの横断確認。
    """
    text = _read(README)
    assert "--extra veo" not in text, "README.md のどこかに `--extra veo` (空 extra) の案内が残存"


@pytest.mark.parametrize(
    "package_name",
    ["Pillow", "pandas", "pyyaml"],
    ids=["Pillow", "pandas", "pyyaml"],
)
def test_main_dependency_listed_in_pyproject(package_name: str) -> None:
    """Given pyproject.toml `[project] dependencies`
    When テストが import する main dep を列挙する
    Then 列挙された dep (`Pillow` / `pandas` / `pyyaml`) が含まれている。

    README に「main deps に入っている」と書いた根拠を pyproject.toml 側でも担保する。
    将来誰かが pyproject.toml から削除した場合、この test と README の説明が同時に乖離する。
    """
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
