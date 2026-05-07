"""Issue #137: intro skill 内 `_common.resolve_repo_root` の単一ソース性 (J 節)。

`resolve_repo_root` は `.claude/skills/intro/references/_common.py` に 1 箇所
だけ定義され、`generate_intro.py` と `generate_droplet_png.py` の両方が
`from _common import resolve_repo_root` で **同じオブジェクト** を再利用する。
本テストは architect-review の指摘 `ARCH-NEW-resolve-repo-root-dry`
(family_tag: `dry-violation`) の再発防止として、

  - 重複定義の禁止
  - 両スクリプトが同一 import 経路を経由していること
  - resolve_repo_root の探索ロジックが意図通り動作すること

を担保する。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._skill_loader import load_skill_script

_REPO_ROOT = Path(__file__).resolve().parent.parent
_INTRO_REFS = _REPO_ROOT / ".claude" / "skills" / "intro" / "references"


# ---------- J-1: `def resolve_repo_root` が _common.py 1 箇所のみ ----------


def test_resolve_repo_root_is_defined_only_in_common_module() -> None:
    """Given `.claude/skills/intro/references/` 配下の Python ソース
    When `def (?:_)?resolve_repo_root` を全件 grep
    Then 定義は `_common.py` の 1 箇所だけで、generate_intro.py /
        generate_droplet_png.py には残存しない (DRY 違反の再発防止)。
    """
    pattern = re.compile(r"^def\s+(?:_)?resolve_repo_root\b", re.MULTILINE)
    definitions: list[tuple[str, int]] = []
    for py in sorted(_INTRO_REFS.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            definitions.append((py.name, line_no))

    assert len(definitions) == 1, (
        f"resolve_repo_root の定義が複数箇所に存在する (DRY 違反): {definitions}"
    )
    assert definitions[0][0] == "_common.py", (
        f"resolve_repo_root の定義が _common.py 以外にある: {definitions}"
    )


# ---------- J-2: 両スクリプトが _common.resolve_repo_root を共有する ----------


def test_generate_intro_and_droplet_share_the_same_resolve_repo_root() -> None:
    """Given generate_intro / generate_droplet_png の両モジュールを load
    When それぞれの `resolve_repo_root` を比較
    Then `_common.resolve_repo_root` 1 つに収束していること
        (= 同一関数オブジェクトが両モジュールから参照される)。
    """
    intro_mod = load_skill_script("intro", "generate_intro")
    droplet_mod = load_skill_script("intro", "generate_droplet_png")

    assert intro_mod.resolve_repo_root is droplet_mod.resolve_repo_root, (
        "resolve_repo_root が両モジュールで異なる object になっている "
        "(再 import / 再定義が発生していないか確認)"
    )
    # 同モジュール由来であることも明示的にチェック
    assert intro_mod.resolve_repo_root.__module__.endswith("_common"), (
        f"resolve_repo_root の __module__ が _common 由来でない: "
        f"{intro_mod.resolve_repo_root.__module__}"
    )


# ---------- J-3: resolve_repo_root の探索ロジック ----------


def test_resolve_repo_root_finds_meta_json_ancestor(tmp_path: Path) -> None:
    """Given 入れ子ディレクトリの上位に `config/channel/meta.json` がある状態
    When _common.resolve_repo_root(<深い nested dir>) を呼ぶ
    Then `meta.json` を持つ祖先 dir が返る。
    """
    intro_mod = load_skill_script("intro", "generate_intro")

    repo = tmp_path / "repo"
    (repo / "config" / "channel").mkdir(parents=True)
    (repo / "config" / "channel" / "meta.json").write_text("{}", encoding="utf-8")

    deep = repo / "a" / "b" / "c"
    deep.mkdir(parents=True)

    resolved = intro_mod.resolve_repo_root(deep)
    assert resolved == repo.resolve(), (
        f"resolve_repo_root が想定 ancestor を返さない: {resolved} != {repo.resolve()}"
    )


def test_resolve_repo_root_raises_when_meta_json_absent(tmp_path: Path) -> None:
    """Given 祖先方向に `config/channel/meta.json` が一切存在しない
    When resolve_repo_root を呼ぶ
    Then FileNotFoundError が raise される (Fail Fast)。
    """
    intro_mod = load_skill_script("intro", "generate_intro")
    isolated = tmp_path / "no_repo_marker"
    isolated.mkdir()

    with pytest.raises(FileNotFoundError):
        intro_mod.resolve_repo_root(isolated)
