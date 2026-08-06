"""`/wf-auto` canonical action の AI timing 実行契約を検証する。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

SKILL_MD = REPO_ROOT / ".claude" / "skills" / "wf-auto" / "SKILL.md"


def _section(text: str, heading: str) -> str:
    match = re.search(
        rf"^{re.escape(heading)}\n(?P<body>.*?)(?=^##\s|\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError(f"`{heading}` セクションが見つかりません")
    return match.group("body")


def test_canonical_action_records_one_closed_ai_segment_for_every_status() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    contract = _section(text, "### canonical action の AI timing 契約")
    steps = _section(text, "## 実行手順")

    assert "`heartbeat` が `owner` を確認した直後" in contract
    assert "子 skill への委譲または terminal action の処理を始める直前" in contract
    assert "datetime.now(UTC).isoformat()" in contract
    assert "<current-attempt-ai-started-at>" in contract
    assert "同じ attempt" in contract
    for status in ("success", "blocked", "failed"):
        assert f"`{status}`" in contract
    assert "AI 区間を必ず閉じる" in contract
    assert "`blocked` / `complete` の terminal action" in contract
    assert "collection 作成前の `record-bootstrap --status blocked|failed`" in contract
    assert "not-owner` なら開始時刻を取得せず" in steps

    bootstrap = next(line for line in steps.splitlines() if "`record-bootstrap --status blocked" in line)
    assert "--ai-started-at <current-attempt-ai-started-at>" in bootstrap


def test_validation_failure_cannot_be_recorded_as_success() -> None:
    contract = _section(SKILL_MD.read_text(encoding="utf-8"), "### canonical action の AI timing 契約")

    validation = contract.index("期待成果物と state を検証")
    status_decision = contract.index("終了 status を決める")
    assert validation < status_decision
    assert "検証に成功した場合だけ `success`" in contract
    assert "検証失敗を含むその他の失敗は `failed`" in contract


def test_retry_uses_a_new_attempt_without_overwriting_failed_timing() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    contract = _section(text, "### canonical action の AI timing 契約")
    resume = _section(text, "## 再開と停止報告")

    assert "新しい開始時刻" in contract
    assert "新しい attempt として追記" in contract
    assert "前回の開始時刻を再利用せず" in contract
    assert "前回の `failed` / `blocked` attempt と実行時間を履歴に残す" in contract
    assert "前回の失敗時間を上書きしない" in resume


def test_existing_workflow_gates_remain_explicit() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    gates = _section(text, "## Hard Gates")
    steps = _section(text, "## 実行手順")

    for gate in ("lease 必須", "対象を固定", "公開許可の正は config だけ"):
        assert gate in gates
    assert "`finally` 相当" in steps
    assert "`release`" in steps
