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
SUNO_LYRIC_SKILL_MD = _REPO_ROOT / ".claude" / "skills" / "suno-lyric" / "SKILL.md"
REVIEW_RUBRIC_MD = _REPO_ROOT / ".claude" / "skills" / "suno-lyric" / "references" / "review-rubric.md"


def _read(path: Path = SKILL_MD) -> str:
    return path.read_text(encoding="utf-8")


def _assert_before(text: str, earlier: str, later: str) -> None:
    earlier_index = text.find(earlier)
    later_index = text.find(later)
    assert earlier_index != -1, f"`{earlier}` が見つからない"
    assert later_index != -1, f"`{later}` が見つからない"
    assert earlier_index < later_index, f"`{earlier}` が `{later}` より前に記載されていない"


def test_skill_md_exists() -> None:
    """Given リポジトリ
    When suno SKILL.md を探す
    Then ファイルが存在する。
    """
    assert SKILL_MD.exists(), f"{SKILL_MD} が存在しません"


def test_suno_lyric_skill_md_exists() -> None:
    """Given リポジトリ
    When suno-lyric SKILL.md を探す
    Then ファイルが存在する。
    """
    assert SUNO_LYRIC_SKILL_MD.exists(), f"{SUNO_LYRIC_SKILL_MD} が存在しません"


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


def test_suno_lyric_documents_generator_reviewer_contract() -> None:
    """Issue #1485: /suno-lyric の生成と意味的品質検証は別コンテキストで行う。"""
    text = _read(SUNO_LYRIC_SKILL_MD)
    for token in (
        "Generator-Reviewer Quality Gate",
        "generator",
        "reviewer",
        "subagent",
        "Codex",
        "別コンテキスト",
        "suno-lyrics.json",
        "suno-lyrics.json` と `references/review-rubric.md` のみ",
    ):
        assert token in text, f"/suno-lyric SKILL.md に generator-reviewer 契約がない（`{token}` 不在）"


def test_suno_lyric_json_contract_supplies_reviewer_context() -> None:
    """Issue #1485: reviewer が成果物 JSON だけでルーブリック観点を検証できる。"""
    text = _read(SUNO_LYRIC_SKILL_MD)
    for token in (
        "review_context",
        "reviewer-only",
        "collection_theme",
        "scene",
        "mood",
        "persona_target",
        "persona_vocabulary",
        "quote_essence",
        "`/suno` の merge loader は `name` / `lyrics` だけを使用",
    ):
        assert token in text, f"/suno-lyric の JSON contract に reviewer context 契約がない（`{token}` 不在）"


def test_suno_lyric_documents_verify_before_semantic_review() -> None:
    """Issue #1485: /suno-lyric は yt-suno-verify 通過後に LLM semantic review へ進む。"""
    text = _read(SUNO_LYRIC_SKILL_MD)
    _assert_before(text, "yt-suno-verify <collection>", "LLM semantic review")


def test_suno_lyric_documents_pass_fail_loop_contract() -> None:
    """Issue #1485: /suno-lyric は entry ごとの PASS / FAIL と上限 2 周の再生成を固定する。"""
    text = _read(SUNO_LYRIC_SKILL_MD)
    for token in ("entry ごと", "PASS", "FAIL", "理由", "FAIL` entry のみ", "最大 2 周", "残課題", "ユーザー"):
        assert token in text, f"/suno-lyric SKILL.md に PASS/FAIL ループ契約がない（`{token}` 不在）"


def test_suno_documents_generator_reviewer_contract_for_style_prompts() -> None:
    """Issue #1485: /suno の Style プロンプトも別コンテキスト reviewer が成果物 JSON だけで検証する。"""
    text = _read()
    for token in (
        "Generator-Reviewer Quality Gate",
        "generator",
        "reviewer",
        "subagent",
        "Codex",
        "別コンテキスト",
        "suno-prompts.json",
        "suno-prompts.json` と `/suno-lyric` の `references/review-rubric.md` のみ",
    ):
        assert token in text, f"/suno SKILL.md に Style prompt review 契約がない（`{token}` 不在）"


def test_suno_json_only_review_uses_existing_prompt_fields() -> None:
    """Issue #1485: /suno reviewer は既存 suno-prompts.json fields だけを読む。"""
    text = _read()
    for token in (
        "`name`, `style`, `lyrics`",
        "More Options 補助 field",
        "`/suno` reviewer は `review_context` を要求せず",
        "外部資料で補完しない",
    ):
        assert token in text, f"/suno reviewer の JSON-only 入力契約が不明確（`{token}` 不在）"


def test_suno_documents_verify_before_semantic_review() -> None:
    """Issue #1485: /suno は yt-suno-verify 通過後に LLM semantic review へ進む。"""
    text = _read()
    _assert_before(text, "yt-suno-verify <collection>", "LLM semantic review")


def test_suno_documents_pass_fail_loop_contract() -> None:
    """Issue #1485: /suno は entry ごとの PASS / FAIL と上限 2 周の再生成を固定する。"""
    text = _read()
    for token in ("entry ごと", "PASS", "FAIL", "理由", "FAIL` entry のみ", "最大 2 周", "残課題", "ユーザー"):
        assert token in text, f"/suno SKILL.md に PASS/FAIL ループ契約がない（`{token}` 不在）"


def test_suno_updates_generated_state_only_after_semantic_review_passes() -> None:
    """Issue #1485: /suno は semantic review 全 PASS 後だけ生成完了 state を更新する。"""
    text = _read()
    step_2_match = re.search(
        r"### Step 2: スクリプトで suno-prompts\.md を生成\b.*?(?=^### Step 3:)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert step_2_match, "SKILL.md に `/suno` Step 2 節が見つからない"
    step_2 = step_2_match.group(0)

    for token in (
        "この保存時点では、まだ `workflow-state.json` の `music.generated = true` に更新しない",
        "全 entry が `PASS` した後にだけ `workflow-state.json` の `music.generated = true` に更新する",
        "`music.generated` を更新せず",
        "Step 3 へ進まず",
    ):
        assert token in step_2, f"/suno Step 2 に生成完了 state のゲート契約がない（`{token}` 不在）"

    _assert_before(step_2, "LLM semantic review", "`music.generated = true` に更新する")


def test_review_rubric_documents_required_semantic_viewpoints() -> None:
    """Issue #1485: references/ に意味的品質検証ルーブリックを固定する。"""
    assert REVIEW_RUBRIC_MD.exists(), f"{REVIEW_RUBRIC_MD} が存在しません"
    text = _read(REVIEW_RUBRIC_MD)
    for token in (
        "テーマ・名言エッセンスの反映度",
        "曲間の同質化",
        "Section tag 構成の妥当性",
        "不自然な表現・禁止表現",
        "suno-lyrics.json",
        "suno-prompts.json",
        "PASS | FAIL",
        "FAIL` entry のみ",
        "2 周",
        "yt-suno-verify",
    ):
        assert token in text, f"review-rubric.md に必須観点またはループ契約がない（`{token}` 不在）"


def test_review_rubric_is_connected_to_json_only_reviewer_context() -> None:
    """Issue #1485: rubric の必須観点は成果物 JSON 内の context から判定する。"""
    text = _read(REVIEW_RUBRIC_MD)
    for token in (
        "JSON-only 入力契約",
        "review_context",
        "collection_theme",
        "scene",
        "mood",
        "persona_target",
        "persona_vocabulary",
        "quote_essence",
        "外部資料で補完せず `FAIL`",
    ):
        assert token in text, f"review-rubric.md が JSON-only context と必須観点を接続していない（`{token}` 不在）"


def test_review_rubric_scopes_suno_to_existing_prompt_fields() -> None:
    """Issue #1485: /suno rubric は suno-prompts.json に実在する field だけで判定する。"""
    text = _read(REVIEW_RUBRIC_MD)
    for token in (
        "`/suno` の `suno-prompts.json` は既存 consumer 互換",
        "`name`, `style`, `lyrics`",
        "More Options",
        "`/suno` entry に `review_context` は要求しない",
        "`review_context` 欠落だけを理由に `FAIL` しない",
        "`/suno` `PASS`",
    ):
        assert token in text, f"review-rubric.md が /suno の実在 field scope を固定していない（`{token}` 不在）"
