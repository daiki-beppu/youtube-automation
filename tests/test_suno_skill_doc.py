"""`.claude/skills/suno/SKILL.md` が issue #692 の新フロー + fallback を記載するかを検証する。

issue #692 受け入れ基準: 「`.claude/skills/suno/SKILL.md` に新フローと fallback が記載されている」。

過去の iteration で SKILL.md が protected-path により未編集のまま REJECT が継続した
(family_tag: spec-noncompliance)。SKILL.md 本文はコード由来テストの対象外で、未反映でも
全テストが pass してしまうため、ドキュメント契約をこのテストで機械的に担保し再発を防ぐ。

検証する契約:
1. Chrome 拡張 + `yt-collection-serve` の自動投入フロー（Step 3）が記載されている。
2. 拡張が使えない／壊れたとき向けの手コピペ fallback 節が記載されている。
3. 自動投入が読む配信元 `suno-prompts.json` への言及がある。
"""

from __future__ import annotations

import re
from pathlib import Path

# リポジトリルート (tests/ の親)
_REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = _REPO_ROOT / ".claude" / "skills" / "suno" / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_skill_md_exists() -> None:
    """Given リポジトリ
    When suno SKILL.md を探す
    Then ファイルが存在する。
    """
    assert SKILL_MD.exists(), f"{SKILL_MD} が存在しません"


def test_skill_md_documents_auto_inject_flow() -> None:
    """Given suno SKILL.md
    When 本文を読む
    Then Chrome 拡張 + `yt-collection-serve` の自動投入フロー（Step 3）が記載されている。

    #698: CLI を `yt-suno-serve` → `yt-collection-serve` に rename したため、
    起動コマンド契約（machine-coupled）を新名に追従する。旧名が残っていないことも検証する。
    PR #886: 旧 `Step 2.5` 表記は整数並びへ採番し直し、Step 3 タイトルに `/suno-helper` を露出。
    """
    text = _read()
    for token in ("Step 3", "yt-collection-serve", "suno-helper", "連続実行"):
        assert token in text, f"SKILL.md に新フローの記載がない（`{token}` 不在）"
    assert "--allow-extension suno-helper" in text, "SKILL.md の Step 3 が拡張 ID 自動検出で起動していない"
    assert '--allow-origin "chrome-extension://<EXTENSION_ID>"' in text, (
        "SKILL.md に検出失敗時の allow-origin fallback がない"
    )
    assert "detected extension: suno-helper -> <id> (chrome-extension://<id>)" in text, (
        "SKILL.md に detected extension 起動ログ確認がない"
    )
    assert "GET /auth/token" in text, "SKILL.md に exact origin lock の疎通確認対象 `/auth/token` がない"
    assert "yt-suno-serve" not in text, "SKILL.md に旧 CLI 名 `yt-suno-serve` が残っている（#698 で廃止）"
    assert "Step 2.5" not in text, "SKILL.md に旧 `Step 2.5` 表記が残っている（PR #886 で整数並びへ採番し直し）"


def test_skill_md_documents_wxt_unpacked_load_flow() -> None:
    """Given suno SKILL.md
    When 拡張ロード手順を読む
    Then WXT 化後の build → `.output/chrome-mv3/` unpacked ロード手順が記載されている。

    #697: 素 JS(手書き manifest.json) → WXT 化で manifest は `wxt.config.ts` から
    `.output/chrome-mv3/` に生成されるようになった。旧手順「`extensions/suno-helper/` を
    直接ロード」は同ディレクトリに manifest.json が無く破綻するため、`pnpm build` →
    `.output/chrome-mv3/` を選択する新フローを機械的に担保し再発を防ぐ（family: spec-noncompliance）。
    """
    text = _read()
    for token in ("pnpm build", ".output/chrome-mv3"):
        assert token in text, f"SKILL.md に WXT ロード手順の記載がない（`{token}` 不在）"


def test_skill_md_has_no_dangling_content_js_reference() -> None:
    """Given suno SKILL.md
    When 注入セレクタの保守先記述を読む
    Then 削除済み `content.js` ではなく現 SSOT `extensions/shared/dom.ts` を参照している。

    #697: content.js は削除され注入ロジックは `extensions/shared/dom.ts` に集約された。
    `content.js` の SELECTORS 参照は dangling reference になるため残存を禁止する。
    """
    text = _read()
    assert "content.js" not in text, "SKILL.md に削除済み `content.js` への参照が残っている（#697）"
    assert "shared/dom.ts" in text, "SKILL.md が注入セレクタ SSOT `shared/dom.ts` を参照していない"


def test_skill_md_documents_serve_url_contract() -> None:
    """Given suno SKILL.md
    When 自動投入フローを読む
    Then 拡張が fetch する `suno-prompts.json` 配信元と新サブパス `/suno/prompts.json` の言及がある。

    #698: エンドポイントを `/prompts.json` → `/suno/prompts.json` にサブパス分離。
    """
    text = _read()
    assert "suno-prompts.json" in text, "SKILL.md に配信元 `suno-prompts.json` の言及がない"
    assert "/suno/prompts.json" in text, "SKILL.md に新配信エンドポイント `/suno/prompts.json` の言及がない（#698）"


def test_skill_md_documents_manual_fallback() -> None:
    """Given suno SKILL.md
    When 本文を読む
    Then 拡張が使えないときの手コピペ fallback 節が記載されている。

    PR #886: 旧 `Step 2.5 fallback` を `Step 3 の fallback` に採番し直した。
    """
    text = _read()
    assert "fallback" in text, "SKILL.md に fallback への言及がない"
    match = re.search(
        r"###\s*Step 3 の fallback\b.*?(?=^### |^## |\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert match, "SKILL.md に `### Step 3 の fallback` 節が見つからない"
    fallback_section = match.group(0)
    assert "手コピペ" in fallback_section, "fallback 節に手コピペ手順の記載がない"
    assert "suno-prompts.md" in fallback_section, "fallback 節が手動投入元 `suno-prompts.md` を参照していない"


def test_skill_md_documents_tracks_per_collection_for_instrumental() -> None:
    """Given suno SKILL.md
    When 本文を読む
    Then インストモードが pattern モデルから `tracks_per_collection` ベースに刷新されたことが記載されている。

    本 PR: `/suno-helper` の登場で連続生成 + playlist 一括化が自動化されたため、`/suno` 側の
    `patterns_per_collection × tracks_per_pattern × 2 (Suno 1 Generate = 2 clip)` 入れ子モデルを
    インスト側だけ廃止し、フラットな `tracks_per_collection` 指定 → `ceil(N/2)` 個の独立 entry に
    切り替えた。ボーカルモードは選曲精度のため pattern モデル維持。読み手 (AI / operator) が
    旧モデルで yaml を書き始めないよう、新節タイトルと算出式の存在をここで機械的に担保する。
    """
    text = _read()
    # 新節タイトルの存在 (インストとボーカルが視認できるレベルで明確に分離されていること)
    assert "## 曲数ベース設計（インストモード）" in text, "SKILL.md にインスト用の新節タイトルがない"
    assert "## パターンベース設計（ボーカルモード）" in text, "SKILL.md にボーカル用の節タイトルがない"
    # 新キー `tracks_per_collection` の言及 (config と yaml 上書きの両ルート)
    assert "tracks_per_collection" in text, "SKILL.md に新キー `tracks_per_collection` への言及がない"
    # 算出式 ceil(N/2) の言及 (Suno 1 Generate = 2 clip 仕様の反映確認)
    assert "ceil" in text, "SKILL.md に `ceil(N/2)` 算出式の言及がない"
