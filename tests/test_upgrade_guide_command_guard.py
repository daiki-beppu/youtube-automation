"""Issue #335: v5.5.0 アップグレードガイドとリリースノートテンプレに
`command not found` 偽陽性ガード文言が定着しているかを検証する。

背景:
    v5.5.0 リリース後、ダウンストリーム agent が `uv run yt-config-migrate verify` を
    「v5.5.0 に存在しない CLI」と誤判断し、env 側の不整合 (uv sync 未実行 / 古い venv /
    cache) を「ガイドの誤り」と早合点して追従後確認をスキップする偽陽性が発生した
    (issue #335)。

    再発防止として以下 2 ファイルにガード文言を追加済み (commit 8f89dbf):
      - docs/upgrades/v5.5.0.md (AI プロンプト / 追従後確認リードイン / Q4)
      - .claude/skills/release-notes/references/release-notes-template.md
        (Step 5 ルール / {{VERIFY_BLOCK}} 節 / 必須 Q ルール)

    本テストはガード文言が将来の編集で剥がれることを防ぐリグレッションガード。
    マジックストリングをモジュールトップに `Final` 定数で集約し、剥がし耐性を確保する。

設計参照:
    .takt/runs/20260518-060329-issue-335-bug-docs-v5-5-0-yt-c/reports/test-design.md
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

# リポジトリルート (tests/ の親)
_REPO_ROOT = Path(__file__).resolve().parent.parent

UPGRADE_GUIDE: Final[Path] = _REPO_ROOT / "docs" / "upgrades" / "v5.5.0.md"
RELEASE_NOTES_TEMPLATE: Final[Path] = (
    _REPO_ROOT / ".claude" / "skills" / "release-notes" / "references" / "release-notes-template.md"
)

# ---------- 期待フレーズ定数 ----------

# v5.5.0.md の AI プロンプト Step 5 直下 1 行ガード
AI_PROMPT_EXISTENCE_PHRASE: Final[str] = "v5.5.0 に確実に存在する CLI"
AI_PROMPT_NOT_OUTDATED_PHRASE: Final[str] = "ガイドが古い"

# v5.5.0.md の「■ 追従後に確認すべきこと」リードイン
EXISTENCE_GUARD_LEADIN: Final[str] = "v5.5.0 のリリース時点で entry point として登録済み"

# env 切り分け 3 ステップ
TRIAGE_STEP_1: Final[str] = "uv sync"
TRIAGE_STEP_2: Final[str] = "uv pip list | grep youtube-channels-automation"
TRIAGE_STEP_3_CACHE: Final[str] = "uv cache clean"
TRIAGE_STEP_3_LOCK: Final[str] = "uv lock --upgrade-package youtube-channels-automation"

# Q4 で agent への最終ガードとなる禁止句
SKIP_FORBIDDEN_PHRASE: Final[str] = "追従後確認をスキップしないこと"

# Q4 本文に必要な command not found 系語句
Q4_COMMAND_NOT_FOUND: Final[str] = "command not found"
Q4_NO_MODULE_NAMED: Final[str] = "No module named"

# Q ナンバリング期待集合
EXPECTED_Q_NUMBERS: Final[set[int]] = {1, 2, 3, 4, 5, 6}

# 旧 Q4 → Q5 / 旧 Q5 → Q6 リナンバリング後の本文断片
Q5_BODY_SUBSTRING: Final[str] = ".claude/skills/ に新スキル /playlist が見えない"
Q6_BODY_SUBSTRING: Final[str] = "/masterup を worktree"

# release-notes-template.md のプレースホルダ・必須要素
TEMPLATE_EXISTENCE_PHRASE: Final[str] = "v{{VER}} に確実に存在する CLI"
TEMPLATE_NOT_OUTDATED_PHRASE: Final[str] = "ガイドが古い"
ISSUE_REFERENCE: Final[str] = "issue #335"

TEMPLATE_VERIFY_HEADING: Final[str] = "### 追従後確認"
TEMPLATE_VERIFY_LEADIN_PHRASE: Final[str] = "v{{VER}} のリリース時点で entry point として登録済み"
TEMPLATE_VERIFY_REQUIRED_NOTE: Final[str] = "リリースごとに省略しないこと"

TEMPLATE_TROUBLESHOOT_HEADING: Final[str] = "### トラブルシューティング"
TEMPLATE_MANDATORY_Q_LABEL: Final[str] = "必須 Q"
TEMPLATE_VENV_REBUILD_PHRASE: Final[str] = ".venv"


# ---------- 共通ヘルパー (モジュールローカル) ----------


def _read(path: Path) -> str:
    """UTF-8 で md を読む。存在しなければ FileNotFoundError をそのまま伝播。"""
    return path.read_text(encoding="utf-8")


def _extract_block(text: str, start_marker: str, end_marker: str | None) -> str:
    """`start_marker` 〜 `end_marker` 直前までの区間を返す。end_marker が None なら末尾まで。

    マーカーは行頭から完全一致で探す。見つからなければ AssertionError。
    """
    start = text.find(start_marker)
    if start == -1:
        raise AssertionError(f"start marker {start_marker!r} が本文中に見つかりません")
    if end_marker is None:
        return text[start:]
    end = text.find(end_marker, start + len(start_marker))
    if end == -1:
        raise AssertionError(f"end marker {end_marker!r} が本文中に見つかりません")
    return text[start:end]


def _q_numbers(text: str) -> list[int]:
    """`^Q(\\d+)\\.` 形式の Q 番号を出現順に全件抽出。"""
    return [int(m.group(1)) for m in re.finditer(r"^Q(\d+)\.", text, flags=re.MULTILINE)]


# ---------- 前提: 対象ファイル存在確認 ----------


def test_upgrade_guide_v550_md_exists() -> None:
    """Given v5.5.0 アップグレードガイドのパス
    When ファイルシステムを参照
    Then ファイルが存在する。

    暗黙 skip を避けるため、欠落時は assert で fail させる (FileNotFoundError ではなく
    明示メッセージで誤削除を伝える)。
    """
    assert UPGRADE_GUIDE.exists(), f"{UPGRADE_GUIDE} が存在しない (issue #335 ガード対象ガイドが欠落)"


def test_release_notes_template_md_exists() -> None:
    """Given release-notes テンプレのパス
    When ファイルシステムを参照
    Then ファイルが存在する。
    """
    assert RELEASE_NOTES_TEMPLATE.exists(), (
        f"{RELEASE_NOTES_TEMPLATE} が存在しない (issue #335 ガード対象テンプレが欠落)"
    )


# ---------- ケース 1: AI プロンプト Step 5 直下のガード ----------


def test_v550_guide_ai_prompt_embeds_existence_guard_below_step5() -> None:
    """Given v5.5.0.md の AI プロンプト
    When 「追従後の動作確認」(Step 5) 直後の行を読む
    Then 「v5.5.0 に確実に存在する CLI」「ガイドが古い と判断せず」相当の
        1 行ガードが含まれる (プロンプトだけで作業する agent が最初に読む層)。
    """
    # Arrange
    text = _read(UPGRADE_GUIDE)

    # Assert: 両フレーズが同一文書内に共起している
    assert AI_PROMPT_EXISTENCE_PHRASE in text, (
        f"{UPGRADE_GUIDE} に {AI_PROMPT_EXISTENCE_PHRASE!r} が見つからない (issue #335 ガード文言が剥がれた可能性)"
    )
    assert AI_PROMPT_NOT_OUTDATED_PHRASE in text, (
        f"{UPGRADE_GUIDE} に {AI_PROMPT_NOT_OUTDATED_PHRASE!r} が見つからない (issue #335 ガード文言が剥がれた可能性)"
    )


# ---------- ケース 2: 追従後確認リードイン ----------


def test_v550_guide_verify_section_contains_existence_leadin() -> None:
    """Given v5.5.0.md の「■ 追従後に確認すべきこと」節
    When 検証コマンドブロック手前のリードイン段落を読む
    Then 「v5.5.0 のリリース時点で entry point として登録済み」の明示が含まれる。
    """
    # Arrange
    text = _read(UPGRADE_GUIDE)
    verify_block = _extract_block(
        text,
        start_marker="■ 追従後に確認すべきこと",
        end_marker="■ トラブルシューティング",
    )

    # Assert
    assert EXISTENCE_GUARD_LEADIN in verify_block, (
        f"{UPGRADE_GUIDE} の追従後確認節に {EXISTENCE_GUARD_LEADIN!r} が見つからない "
        "(issue #335 ガード中核の偽陽性防止が剥がれた可能性)"
    )


# ---------- ケース 3: env 切り分け 3 ステップが順番通り ----------


def test_v550_guide_verify_leadin_lists_triage_steps_in_order() -> None:
    """Given v5.5.0.md の追従後確認リードイン段落
    When 3 ステップの env 切り分け手順を読む
    Then `uv sync` → `uv pip list | grep ...` → `uv cache clean && uv lock ...` の
        順序で記載されている (順序が崩れると agent が誤った順で試行する)。
    """
    # Arrange
    text = _read(UPGRADE_GUIDE)
    verify_block = _extract_block(
        text,
        start_marker="■ 追従後に確認すべきこと",
        end_marker="■ トラブルシューティング",
    )

    # Act: 各ステップの最初の出現位置を取得
    idx_1 = verify_block.find(TRIAGE_STEP_1)
    idx_2 = verify_block.find(TRIAGE_STEP_2)
    idx_3_cache = verify_block.find(TRIAGE_STEP_3_CACHE)
    idx_3_lock = verify_block.find(TRIAGE_STEP_3_LOCK)

    # Assert: 全フレーズが存在し、順序が正しい
    assert idx_1 != -1, f"{TRIAGE_STEP_1!r} が追従後確認節に見つからない"
    assert idx_2 != -1, f"{TRIAGE_STEP_2!r} が追従後確認節に見つからない"
    assert idx_3_cache != -1, f"{TRIAGE_STEP_3_CACHE!r} が追従後確認節に見つからない"
    assert idx_3_lock != -1, f"{TRIAGE_STEP_3_LOCK!r} が追従後確認節に見つからない"
    assert idx_1 < idx_2 < idx_3_cache, (
        f"env 切り分け 3 ステップの順序が壊れている (uv sync={idx_1}, pip list={idx_2}, cache clean={idx_3_cache})"
    )
    assert idx_3_cache < idx_3_lock, (
        f"3 ステップ目で uv cache clean({idx_3_cache}) より uv lock({idx_3_lock}) が先行している (順序が壊れている)"
    )


# ---------- ケース 4: Q4 (command not found) 新設 ----------


def test_v550_guide_troubleshooting_q4_is_command_not_found_entry() -> None:
    """Given v5.5.0.md の「■ トラブルシューティング」節
    When Q4 を読む
    Then Q4 が `command not found` / `No module named` 系の質問として新設されており、
        A. に env 切り分け手順 (uv sync / uv pip list / uv cache clean / uv lock) が含まれる。
    """
    # Arrange
    text = _read(UPGRADE_GUIDE)
    troubleshoot_block = _extract_block(
        text,
        start_marker="■ トラブルシューティング",
        end_marker="■ 最終チェックリスト",
    )

    # Act: Q4 ブロックを Q5 直前まで切り出す
    q4_block = _extract_block(troubleshoot_block, start_marker="Q4.", end_marker="Q5.")

    # Assert: Q4 が command not found 系の質問
    assert Q4_COMMAND_NOT_FOUND in q4_block, (
        f"Q4 に {Q4_COMMAND_NOT_FOUND!r} が見つからない (issue #335 で導入した必須 Q が剥がれた可能性)"
    )
    assert Q4_NO_MODULE_NAMED in q4_block, (
        f"Q4 に {Q4_NO_MODULE_NAMED!r} が見つからない (Python import エラー系の網羅が欠落)"
    )

    # Assert: A. に env 切り分け手順が揃っている
    for needle in (TRIAGE_STEP_1, TRIAGE_STEP_2, TRIAGE_STEP_3_CACHE, TRIAGE_STEP_3_LOCK):
        assert needle in q4_block, f"Q4 A に env 切り分けステップ {needle!r} が見つからない"


# ---------- ケース 5: Q4 末尾の禁止句 ----------


def test_v550_guide_troubleshooting_q4_forbids_skipping_post_followup_check() -> None:
    """Given v5.5.0.md の Q4 A
    When 末尾の禁止句を読む
    Then 「追従後確認をスキップしないこと」相当の禁止句が存在する
        (agent への最終ガード。偽陽性早合点の明示的禁止)。
    """
    # Arrange
    text = _read(UPGRADE_GUIDE)
    troubleshoot_block = _extract_block(
        text,
        start_marker="■ トラブルシューティング",
        end_marker="■ 最終チェックリスト",
    )
    q4_block = _extract_block(troubleshoot_block, start_marker="Q4.", end_marker="Q5.")

    # Assert
    assert SKIP_FORBIDDEN_PHRASE in q4_block, (
        f"Q4 A に {SKIP_FORBIDDEN_PHRASE!r} が見つからない (issue #335 偽陽性 agent への最終ガードが剥がれた可能性)"
    )


# ---------- ケース 6: テンプレ Step 5 ルール段落 ----------


def test_release_notes_template_step5_requires_existence_guard_with_issue_link() -> None:
    """Given release-notes-template.md の AI_PROMPT 書き方ガイド Step 5
    When ルール段落を読む
    Then 「v{{VER}} に確実に存在する CLI」「ガイドが古い と判断せず」「issue #335」の
        3 要素が共存している (v5.6 以降の自動付与の根幹)。
    """
    # Arrange
    text = _read(RELEASE_NOTES_TEMPLATE)

    # Assert: 3 要素が同一文書内に共起している
    assert TEMPLATE_EXISTENCE_PHRASE in text, (
        f"{RELEASE_NOTES_TEMPLATE} に {TEMPLATE_EXISTENCE_PHRASE!r} が見つからない "
        "(issue #335 テンプレ側ガードが剥がれた可能性)"
    )
    assert TEMPLATE_NOT_OUTDATED_PHRASE in text, (
        f"{RELEASE_NOTES_TEMPLATE} に {TEMPLATE_NOT_OUTDATED_PHRASE!r} が見つからない"
    )
    assert ISSUE_REFERENCE in text, (
        f"{RELEASE_NOTES_TEMPLATE} に {ISSUE_REFERENCE!r} が見つからない "
        "(根拠 issue リンクが剥がれると将来の編集者が削除する誘惑が増す)"
    )


# ---------- ケース 7: テンプレ {{VERIFY_BLOCK}} 節の必須リードイン ----------


def test_release_notes_template_verify_block_mandates_existence_leadin() -> None:
    """Given release-notes-template.md の「### 追従後確認 ({{VERIFY_BLOCK}})」節
    When 節本文を読む
    Then 必須リードイン (3 ステップ + `v{{VER}}` プレースホルダ) と
        「リリースごとに省略しないこと」が含まれる (将来バージョンで省略不可)。
    """
    # Arrange
    text = _read(RELEASE_NOTES_TEMPLATE)
    verify_block = _extract_block(
        text,
        start_marker=TEMPLATE_VERIFY_HEADING,
        end_marker=TEMPLATE_TROUBLESHOOT_HEADING,
    )

    # Assert: バージョン非依存のリードイン (v{{VER}} 付き)
    assert TEMPLATE_VERIFY_LEADIN_PHRASE in verify_block, (
        f"{RELEASE_NOTES_TEMPLATE} の {{VERIFY_BLOCK}} 節に {TEMPLATE_VERIFY_LEADIN_PHRASE!r} が見つからない"
    )

    # Assert: 3 ステップが含まれる
    for needle in (TRIAGE_STEP_1, TRIAGE_STEP_2, TRIAGE_STEP_3_CACHE):
        assert needle in verify_block, f"{{VERIFY_BLOCK}} 節リードインに {needle!r} が見つからない"

    # Assert: 省略不可宣言
    assert TEMPLATE_VERIFY_REQUIRED_NOTE in verify_block, (
        f"{{VERIFY_BLOCK}} 節に {TEMPLATE_VERIFY_REQUIRED_NOTE!r} が見つからない "
        "(省略不可宣言が剥がれると将来バージョンで削除される)"
    )


# ---------- ケース 8: テンプレ「必須 Q」ルール ----------


def test_release_notes_template_troubleshooting_mandates_command_not_found_q() -> None:
    """Given release-notes-template.md の「### トラブルシューティング」節
    When 「必須 Q」ルールを読む
    Then `command not found` / `No module named` Q を 1 件必ず含める旨が宣言され、
        A. テンプレに env 切り分け 4 ステップ (uv sync / uv pip list /
        uv cache clean + uv lock / .venv 削除) が含まれる。
    """
    # Arrange
    text = _read(RELEASE_NOTES_TEMPLATE)
    troubleshoot_block = _extract_block(
        text,
        start_marker=TEMPLATE_TROUBLESHOOT_HEADING,
        end_marker="### 最終チェックリスト",
    )

    # Assert: 「必須 Q」ラベルの存在
    assert TEMPLATE_MANDATORY_Q_LABEL in troubleshoot_block, (
        f"テンプレ トラブルシューティング節に {TEMPLATE_MANDATORY_Q_LABEL!r} ラベルが"
        "見つからない (将来バージョンで必須化が剥がれる)"
    )

    # Assert: command not found / No module named の明示
    assert Q4_COMMAND_NOT_FOUND in troubleshoot_block, f"必須 Q ルールに {Q4_COMMAND_NOT_FOUND!r} が見つからない"
    assert Q4_NO_MODULE_NAMED in troubleshoot_block, f"必須 Q ルールに {Q4_NO_MODULE_NAMED!r} が見つからない"

    # Assert: env 切り分け 4 ステップ (.venv 削除を含む)
    for needle in (
        TRIAGE_STEP_1,
        TRIAGE_STEP_2,
        TRIAGE_STEP_3_CACHE,
        TRIAGE_STEP_3_LOCK,
        TEMPLATE_VENV_REBUILD_PHRASE,
    ):
        assert needle in troubleshoot_block, f"必須 Q ルール A. に {needle!r} が見つからない"


# ---------- ケース 9: 旧 Q4/Q5 のリナンバリング ----------


def test_v550_guide_legacy_q_entries_are_renumbered_to_q5_and_q6() -> None:
    """Given v5.5.0.md の「■ トラブルシューティング」節
    When Q5 / Q6 本文を読む
    Then 旧 Q4 (新スキル /playlist が見えない) → Q5 に、旧 Q5 (/masterup を worktree) → Q6 に
        リナンバリングされている (order.md「後続 Q はリナンバー」要件)。
    """
    # Arrange
    text = _read(UPGRADE_GUIDE)
    troubleshoot_block = _extract_block(
        text,
        start_marker="■ トラブルシューティング",
        end_marker="■ 最終チェックリスト",
    )
    q5_block = _extract_block(troubleshoot_block, start_marker="Q5.", end_marker="Q6.")
    q6_block = _extract_block(troubleshoot_block, start_marker="Q6.", end_marker=None)

    # Assert
    assert Q5_BODY_SUBSTRING in q5_block, f"Q5 に {Q5_BODY_SUBSTRING!r} が見つからない (リナンバリング不整合)"
    assert Q6_BODY_SUBSTRING in q6_block, f"Q6 に {Q6_BODY_SUBSTRING!r} が見つからない (リナンバリング不整合)"


# ---------- ケース 10: Q ナンバリング整合性 ----------


def test_v550_guide_troubleshooting_q_numbers_are_exactly_1_through_6() -> None:
    """Given v5.5.0.md の「■ トラブルシューティング」節
    When `Q\\d+\\.` パターンを全件抽出
    Then Q1〜Q6 の 6 件のみ存在し、重複・欠番なし (リファクタ時の番号衝突検知)。
    """
    # Arrange
    text = _read(UPGRADE_GUIDE)
    troubleshoot_block = _extract_block(
        text,
        start_marker="■ トラブルシューティング",
        end_marker="■ 最終チェックリスト",
    )

    # Act
    numbers = _q_numbers(troubleshoot_block)

    # Assert: 重複なしの集合一致
    assert set(numbers) == EXPECTED_Q_NUMBERS, (
        f"トラブルシューティング Q ナンバリングが期待集合 {EXPECTED_Q_NUMBERS} と一致しない: actual={sorted(numbers)}"
    )
    assert len(numbers) == len(EXPECTED_Q_NUMBERS), f"Q 番号に重複がある: {numbers}"


# ---------- ケース 11: テンプレ側の issue 参照根拠が複数箇所 ----------


def test_release_notes_template_issue_reference_appears_in_multiple_locations() -> None:
    """Given release-notes-template.md
    When `issue #335` の出現回数を数える
    Then 2 箇所以上に存在する (Step 5 ルール段落 + {{VERIFY_BLOCK}} 以降の必須 Q 節。
        将来 editor がガード文言を剥がそうとした時の根拠追跡性)。
    """
    # Arrange
    text = _read(RELEASE_NOTES_TEMPLATE)

    # Act
    count = text.count(ISSUE_REFERENCE)

    # Assert
    assert count >= 2, (
        f"{RELEASE_NOTES_TEMPLATE} の {ISSUE_REFERENCE!r} 参照が {count} 件しかない "
        "(2 箇所以上必要: Step 5 ルール + 必須 Q 節)"
    )
