"""`.claude/skills/suno/SKILL.md` が issue #692 の新フロー + fallback を記載するかを検証する。

issue #692 受け入れ基準: 「`.claude/skills/suno/SKILL.md` に新フローと fallback が記載されている」。

過去の iteration で SKILL.md が protected-path により未編集のまま REJECT が継続した
(family_tag: spec-noncompliance)。SKILL.md 本文はコード由来テストの対象外で、未反映でも
全テストが pass してしまうため、ドキュメント契約をこのテストで機械的に担保し再発を防ぐ。

検証する契約:
1. Chrome 拡張 + `collection-serve` の自動投入フロー（Step 3）が記載されている。
2. 拡張が使えない／壊れたとき向けの手コピペ fallback 節が記載されている。
3. 自動投入が読む配信元 `suno-prompts.json` への言及がある。
"""

from __future__ import annotations

import re
from pathlib import Path

# リポジトリルート (tests/ の親)
_REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = _REPO_ROOT / ".claude" / "skills" / "suno" / "SKILL.md"
SUNO_HELPER_SKILL_MD = _REPO_ROOT / ".claude" / "skills" / "suno-helper" / "SKILL.md"
WF_NEW_SKILL_MD = _REPO_ROOT / ".claude" / "skills" / "wf-new" / "SKILL.md"
SUNO_HELPER_PHASE_CONSTANTS_TS = _REPO_ROOT / "extensions" / "shared" / "constants.ts"
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


def _read_suno_helper() -> str:
    return SUNO_HELPER_SKILL_MD.read_text(encoding="utf-8")


def _read_wf_new() -> str:
    return WF_NEW_SKILL_MD.read_text(encoding="utf-8")


def _read_phase_constants() -> str:
    return SUNO_HELPER_PHASE_CONSTANTS_TS.read_text(encoding="utf-8")


def _suno_helper_phase_table_values() -> set[str]:
    text = _read_suno_helper()
    match = re.search(
        r"### Step 5\. 進捗 phase を読む\b.*?\| phase \| 意味 \|(?P<body>.*?)(?=^\*\*phase 遷移の詳細\*\*)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError("suno-helper SKILL.md の phase 表が見つかりません")
    return set(re.findall(r"^\| `([^`]+)` \|", match.group("body"), flags=re.MULTILINE))


def _shared_phase_values() -> set[str]:
    text = _read_phase_constants()
    match = re.search(r"export const PHASE = \{(?P<body>.*?)\} as const;", text, flags=re.DOTALL)
    if not match:
        raise AssertionError("extensions/shared/constants.ts の PHASE 定義が見つかりません")
    return set(re.findall(r': "([^"]+)"', match.group("body")))


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
    Then Chrome 拡張 + `collection-serve` の自動投入フロー（Step 3）が記載されている。

    PR #1574: `--allow-extension` は Python の `yt-collection-serve` に実装されているため、
    起動コマンド契約（machine-coupled）は実在 CLI を固定する。
    PR #886: 旧 `Step 2.5` 表記は整数並びへ採番し直し、Step 3 タイトルに `/suno-helper` を露出。
    """
    text = _read()
    for token in ("Step 3", "collection-serve", "suno-helper", "連続実行"):
        assert token in text, f"SKILL.md に新フローの記載がない（`{token}` 不在）"
    assert "uv run yt-collection-serve" in text, "SKILL.md の Step 3 が実在する collection-serve CLI を使っていない"
    assert "--allow-extension suno-helper" in text, "SKILL.md の Step 3 が拡張 ID 自動検出で起動していない"
    assert '--allow-origin "chrome-extension://<EXTENSION_ID>"' in text, (
        "SKILL.md に検出失敗時の allow-origin fallback がない"
    )
    assert "Preferences JSON parse failure" in text, "SKILL.md に Preferences JSON parse failure 時の fallback がない"
    assert "detected extension: suno-helper -> <id> (chrome-extension://<id>)" in text, (
        "SKILL.md に detected extension 起動ログ確認がない"
    )
    assert "GET /auth/token" in text, "SKILL.md に exact origin lock の疎通確認対象 `/auth/token` がない"
    assert "yt-suno-serve" not in text, "SKILL.md に旧 CLI 名 `yt-suno-serve` が残っている（#698 で廃止）"
    assert "bunx tayk collection-serve" not in text, "SKILL.md が未実装の `tayk collection-serve` を案内している"
    assert "Step 2.5" not in text, "SKILL.md に旧 `Step 2.5` 表記が残っている（PR #886 で整数並びへ採番し直し）"


def test_skill_md_documents_wxt_unpacked_load_flow() -> None:
    """Given suno SKILL.md
    When 拡張ロード手順を読む
    Then WXT 化後の build 成果物を安定 basename の unpacked directory としてロードする手順が記載されている。

    #697: 素 JS(手書き manifest.json) → WXT 化で manifest は `wxt.config.ts` から
    `.output/chrome-mv3/` に生成されるが、`--allow-extension suno-helper` は Chrome Preferences の
    path basename を照合する。ロードする unpacked directory は `suno-helper` basename でなければならない。
    """
    text = _read()
    for token in (
        "npx -y pnpm@11.11.0 -C extensions/suno-helper build",
        ".output/chrome-mv3",
        "~/chrome-extensions/suno-helper",
    ):
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
    Then dir mode で拡張が fetch する collection-scoped `suno-prompts.json` 配信元の言及がある。

    #816: dir mode は `/collections` と `/collections/<id>/suno/prompts.json` を配信し、
    `/suno/prompts.json` は single file mode 専用で 404 になる。
    """
    text = _read()
    assert "suno-prompts.json" in text, "SKILL.md に配信元 `suno-prompts.json` の言及がない"
    assert "/collections/<id>/suno/prompts.json" in text, (
        "SKILL.md に dir mode の collection-scoped prompts endpoint がない"
    )
    assert "http://localhost:7873/suno/prompts.json" not in text, (
        "SKILL.md が dir mode で 404 になる `/suno/prompts.json` 直 URL を案内している"
    )


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
    インストモードをフラットな `tracks_per_collection` 指定 → `ceil(N/2)` 個の独立 entry に
    切り替えた。読み手 (AI / operator) が旧モデルで yaml を書き始めないよう、新節タイトルと
    算出式の存在をここで機械的に担保する。
    """
    text = _read()
    # 新節タイトルの存在 (インストとボーカルが視認できるレベルで明確に分離されていること)
    assert "## 曲数ベース設計（インストモード）" in text, "SKILL.md にインスト用の新節タイトルがない"
    assert "## パターンベース設計（ボーカルモード）" in text, "SKILL.md にボーカル用の節タイトルがない"
    # 新キー `tracks_per_collection` の言及 (config と yaml 上書きの両ルート)
    assert "tracks_per_collection" in text, "SKILL.md に新キー `tracks_per_collection` への言及がない"
    # 算出式 ceil(N/2) の言及 (Suno 1 Generate = 2 clip 仕様の反映確認)
    assert "ceil" in text, "SKILL.md に `ceil(N/2)` 算出式の言及がない"


def test_suno_helper_documents_browser_use_primary_flow() -> None:
    """Given suno-helper SKILL.md
    When agent 操作用手順を読む
    Then browser use 主経路で開始・操作・監視できる粒度の flow が記載されている。
    """
    text = _read_suno_helper()
    for token in (
        "Agent primary flow: browser use",
        "yt-collection-serve",
        "https://suno.com/create",
        '[data-suno-helper="control-panel"]',
        '[data-suno-control="server-url"]',
        '[data-suno-control="collection-select"]',
        '[data-suno-control="fetch-data"]',
        '[data-suno-control="run"]',
        "data-suno-phase",
        'role="status"',
        "finished",
        "stopped",
        "error",
    ):
        assert token in text, f"suno-helper SKILL.md に browser use 主経路の記載がない（`{token}` 不在）"


def test_suno_helper_devtools_mcp_is_not_required_flow() -> None:
    """Given suno-helper SKILL.md
    When DevTools MCP の扱いを読む
    Then 必須手順ではなく診断・補助・フォールバック扱いとして固定されている。
    """
    text = _read_suno_helper()
    assert "Chrome DevTools MCP は必須ではない" in text
    assert "診断・補助・フォールバック" in text
    forbidden = re.compile(r"DevTools MCP[^。\n]*(必須手順|主経路)|必ず[^。\n]*DevTools MCP")
    assert not forbidden.search(text), "Chrome DevTools MCP が必須手順または主経路として記載されている"


def test_suno_helper_documents_handoff_and_no_infinite_wait_rules() -> None:
    """Given suno-helper SKILL.md
    When 生成中の監視手順を読む
    Then agent が手動介入要否を判断し、無限待機を避ける条件が記載されている。
    """
    text = _read_suno_helper()
    for token in (
        "無限待機を避ける監視ルール",
        "handoff 条件",
        "ログイン",
        "CAPTCHA",
        "拡張がロードされていない",
        "server 接続失敗",
        "生成が `stopped`",
        "playlist 追加失敗",
        "ZIP ダウンロードが失敗",
    ):
        assert token in text, f"suno-helper SKILL.md に handoff / 待機判断の記載がない（`{token}` 不在）"


def test_suno_helper_phase_table_matches_shared_phase_constants() -> None:
    """Given suno-helper SKILL.md と shared PHASE
    When 進捗 phase 表を照合する
    Then runner が emit する全 phase が agent 監視手順に記載されている。
    """
    assert _suno_helper_phase_table_values() == _shared_phase_values()


def test_wf_new_hands_off_to_suno_helper_browser_use_flow() -> None:
    """Given wf-new SKILL.md
    When Suno 後続案内を読む
    Then user 操作前提ではなく /suno-helper の browser use 主経路へ接続している。
    """
    text = _read_wf_new()
    for token in (
        "`/suno-helper` が browser use",
        "次工程として `/suno-helper` の browser use 主導フロー",
        "suno-helper overlay / popup",
        "handoff 条件は `/suno-helper` 側",
    ):
        assert token in text, f"wf-new SKILL.md が suno-helper browser use 導線へ追従していない（`{token}` 不在）"
    for legacy in (
        "Chrome 拡張でのブラウザ実行だけを user に引き継ぐ",
        "`/wf-new` は Suno 用 server 起動までで user に引き継ぐ",
        "user 操作に委ねる",
    ):
        assert legacy not in text, f"wf-new SKILL.md に user 操作前提の旧文言が残っている（`{legacy}`）"


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
    """Issue #1485: /suno-lyric は uv run yt-suno-verify 通過後に LLM semantic review へ進む。"""
    text = _read(SUNO_LYRIC_SKILL_MD)
    _assert_before(text, "uv run yt-suno-verify <collection-path>", "LLM semantic review")


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
    """Issue #1485: /suno は uv run yt-suno-verify 通過後に LLM semantic review へ進む。"""
    text = _read()
    _assert_before(text, "uv run yt-suno-verify <collection-path>", "LLM semantic review")


def test_suno_documents_pass_fail_loop_contract() -> None:
    """Issue #1485: /suno は entry ごとの PASS / FAIL と上限 2 周の再生成を固定する。"""
    text = _read()
    for token in ("entry ごと", "PASS", "FAIL", "理由", "FAIL` entry のみ", "最大 2 周", "残課題", "ユーザー"):
        assert token in text, f"/suno SKILL.md に PASS/FAIL ループ契約がない（`{token}` 不在）"


def test_suno_blocks_step_3_until_semantic_review_passes() -> None:
    """Issue #1485: /suno は semantic review 全 PASS 後だけ Suno UI 投入へ進む。"""
    text = _read()
    step_2_match = re.search(
        r"### Step 2: スクリプトで suno-prompts\.md を生成\b.*?(?=^### Step 3:)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert step_2_match, "SKILL.md に `/suno` Step 2 節が見つからない"
    step_2 = step_2_match.group(0)

    for token in (
        "`workflow-state.json` の `assets.music_prompts = true` に更新する",
        "全 entry が `PASS` した後にだけ Suno UI へ投入する",
        "Step 3 へ進まず",
    ):
        assert token in step_2, f"/suno Step 2 に semantic review gate 契約がない（`{token}` 不在）"

    _assert_before(step_2, "LLM semantic review", "Suno UI へ投入する")


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
        "uv run yt-suno-verify",
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
