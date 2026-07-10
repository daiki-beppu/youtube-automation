"""`comments-reply` の Generator-Reviewer 品質ゲート契約を検証する。"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = _REPO_ROOT / ".claude" / "skills" / "comments-reply" / "SKILL.md"
REVIEW_RUBRIC_MD = SKILL_MD.parent / "references" / "review-rubric.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_tokens_in_order(text: str, tokens: tuple[str, ...]) -> None:
    cursor = -1
    for token in tokens:
        index = text.find(token, cursor + 1)
        assert index != -1, f"`{token}` が見つかりません"
        assert index > cursor, f"`{token}` の記載順が不正です"
        cursor = index


def test_reviewer_phase_is_between_author_and_dry_run() -> None:
    text = _read(SKILL_MD)

    _assert_tokens_in_order(
        text,
        (
            "### Phase 3: Agent ツールで返信 JSON を作成",
            "### Phase 4: 別コンテキスト Reviewer で品質ゲート",
            "### Phase 5: dry-run で内容をプレビュー",
            "### Phase 6: apply で反映",
        ),
    )
    reviewer_phase = text.split("### Phase 4:", 1)[1].split("### Phase 5:", 1)[0]
    assert "Author と会話コンテキストを共有しない" in reviewer_phase
    assert "`/tmp/comment-replies.json` と `references/review-rubric.md` **だけ**" in reviewer_phase


def test_review_contract_covers_all_four_criteria_and_counts() -> None:
    skill = _read(SKILL_MD)
    rubric = _read(REVIEW_RUBRIC_MD)

    assert "候補 JSON と `config/channel/comments.json` の正規値から `review_context` を付加" in skill
    for field in ("comment_text", "channel_persona", "ng_words", "max_length", "language"):
        assert f'"{field}"' in skill
        assert f"`{field}`" in rubric
    for criterion in ("persona", "ng_words", "max_length", "language"):
        assert f"**{criterion}**" in rubric
    for token in ("PASS", "FAIL", "pass_count", "fail_count"):
        assert token in skill
        assert token in rubric
    assert "untrusted data" in rubric
    assert "大文字小文字を無視した部分一致" in rubric
    assert "`comment_text` と `reply_text` の主言語をそれぞれ検出" in rubric


def test_language_review_is_not_replaced_by_static_detection() -> None:
    skill = _read(SKILL_MD)
    rubric = _read(REVIEW_RUBRIC_MD)
    out_of_scope = skill.split("## 非スコープ", 1)[1]

    assert "Reviewer の主言語比較を langdetect 等の非 AI・静的判定へ置き換えること" in out_of_scope
    assert "判定が曖昧な場合だけ `comments.language` をヒントに使う" in out_of_scope
    assert "検出が曖昧な場合だけ、JSON 内の `language` を言語ヒントとして用いる" in rubric
    assert "langdetect 等の自動言語判定" not in out_of_scope


def test_failed_replies_are_retried_twice_then_excluded_with_reasons() -> None:
    text = _read(SKILL_MD)
    reviewer_phase = text.split("### Phase 4:", 1)[1].split("### Phase 5:", 1)[0]

    assert "`FAIL` の `comment_id` だけ" in reviewer_phase
    assert "PASS 済みの" in reviewer_phase
    assert "Author が返す更新値は FAIL した `reply_text` だけに限定" in reviewer_phase
    assert "既存行の `review_context` を変更せずに `reply_text` だけを置き換える" in reviewer_phase
    assert "Author が `review_context` を返しても\n採用してはならない" in reviewer_phase
    assert "候補 JSON と\n`config/channel/comments.json` から同じ `comment_id` の正規値を復元" in reviewer_phase
    assert "`required_context` を理由としてその reply を除外一覧へ追加" in reviewer_phase
    assert "最大 2 周" in reviewer_phase
    assert "`/tmp/comment-replies.json` から除外" in reviewer_phase
    assert "除外した `comment_id`、FAIL 基準、最終理由" in reviewer_phase


def test_dry_run_approval_summary_identifies_reviewer_exclusions() -> None:
    text = _read(SKILL_MD)
    dry_run_phase = text.split("### Phase 5:", 1)[1].split("### 承認ゲート:", 1)[0]
    approval_gate = text.split("### 承認ゲート:", 1)[1].split("### Phase 6:", 1)[0]

    assert "Reviewer 起因の除外一覧と `comment_id` が一致" in dry_run_phase
    assert "Reviewer 起因の除外件数と理由一覧" in approval_gate
    assert "一次品質フィルタを通過済み" in approval_gate
    assert "承認されるまで Phase 6 を絶対に実行しない" in approval_gate
