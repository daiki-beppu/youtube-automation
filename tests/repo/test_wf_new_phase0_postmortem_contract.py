"""`/wf-new` Phase 0 の未 postmortem 分析契約を検証する。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

SKILL = REPO_ROOT / ".claude" / "skills" / "wf-new" / "SKILL.md"
CHEATSHEET = REPO_ROOT / "docs" / "workflow-cheatsheet.md"
FLOP_MODE = REPO_ROOT / ".claude" / "skills" / "analytics" / "references" / "flop.md"


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    match = re.search(
        rf"^{re.escape(heading)}\n(?P<body>.*?)(?=^##\s|\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert match is not None, f"section not found: {heading}"
    return match.group("body")


def test_phase_zero_runs_after_hard_gates_and_before_pilot_and_planning() -> None:
    text = _text()

    positions = [
        text.index("## Hard Gates"),
        text.index("## Phase 0: 直近サイクルの振り返り"),
        text.index("## 任意: パイロット検証確認"),
        text.index("### Phase 1: 企画"),
    ]
    assert positions == sorted(positions)


def test_phase_zero_lists_all_candidates_and_reports_non_blocking_reasons() -> None:
    phase_zero = _section(_text(), "## Phase 0: 直近サイクルの振り返り")

    assert "uv run yt-postmortem-pending --json" in phase_zero
    assert "出力順" in phase_zero
    assert "pending が 0 件" in phase_zero
    assert "unanalyzable" in phase_zero
    assert "reason ごとの内訳" in phase_zero
    assert "停止理由にしない" in phase_zero
    for reason in (
        "upload_tracking_missing",
        "video_id_missing",
        "analytics_data_missing",
        "video_not_in_analytics",
    ):
        assert reason in phase_zero


def test_phase_zero_requires_execution_approval_or_records_unattended_block() -> None:
    phase_zero = _section(_text(), "## Phase 0: 直近サイクルの振り返り")

    assert "対象 collection 名" in phase_zero
    assert "pending 件数" in phase_zero


def test_phase_zero_offers_two_choices_and_uses_agent_inference() -> None:
    phase_zero = _section(_text(), "## Phase 0: 直近サイクルの振り返り")

    assert "実行する" in phase_zero
    assert "今回はスキップ" in phase_zero
    assert "2択" in phase_zero
    assert "Vertex AI ありで実行" not in phase_zero
    assert "Vertex AI なしで実行" not in phase_zero
    assert "--no-vertex" not in phase_zero
    assert "1 件あたり最大 1 call" not in phase_zero
    assert "postmortem.md" in phase_zero
    assert "data/insights.jsonl" in phase_zero
    assert "無人実行" in phase_zero
    assert "承認を省略しない" in phase_zero
    assert "record-bootstrap --status blocked" in phase_zero
    assert "pending 件数" in phase_zero


def test_phase_zero_delegates_serially_and_fails_closed_on_each_artifact() -> None:
    phase_zero = _section(_text(), "## Phase 0: 直近サイクルの振り返り")

    assert "`/analytics --flop <collection>`" in phase_zero
    assert "Agent ツール" in phase_zero
    assert "並列 Agent は使わない" in phase_zero
    assert "workflow-state.json" in phase_zero
    assert "AskUserQuestion" in phase_zero
    assert "子 skill 固有の承認" in phase_zero
    assert "メインが AskUserQuestion" in phase_zero
    assert "各委譲の直後" in phase_zero
    assert "20-documentation/postmortem.md" in phase_zero
    assert "残りの pending を実行しない" in phase_zero
    assert "uv run yt-init-collection" in phase_zero
    assert "collections/planning/" in phase_zero
    assert "assets.*" in phase_zero
    assert "同じ `/wf-new` を再実行" in phase_zero


def test_phase_zero_validates_insights_only_after_every_postmortem() -> None:
    phase_zero = _section(_text(), "## Phase 0: 直近サイクルの振り返り")

    validator = "uv run python3 .claude/skills/analytics/references/validate_insights.py data/insights.jsonl"
    assert validator in phase_zero
    assert "全件成功後" in phase_zero
    assert "exit 0" in phase_zero
    assert "Phase 1" in phase_zero
    assert "学びの生成・検証を再実装しない" in phase_zero


def test_phase_one_b_consumes_phase_zero_output_without_becoming_a_gate() -> None:
    phase_one = _section(_text(), "## Instructions")

    assert "1-b. **蓄積 insights の収集（open エントリ、gate ではない）**" in phase_one
    assert "Phase 0" in phase_one
    assert "`/analytics --flop`" in phase_one
    assert "自動実行しない" not in phase_one
    assert "/flop-analysis" not in phase_one

    flop_mode = FLOP_MODE.read_text(encoding="utf-8")
    assert "`/wf-new` Phase 0" in flop_mode


def test_api_estimate_and_cheatsheet_expose_phase_zero() -> None:
    api_calls = _section(_text(), "## 想定 API call 数")
    cheatsheet = CHEATSHEET.read_text(encoding="utf-8")

    assert "Phase 0" in api_calls
    assert "Vertex AI 0 call（ローカル CLI + agent 推論のみ）" in api_calls
    assert "--no-vertex" not in api_calls
    assert "/analytics --flop" in api_calls
    assert "Phase 0" in cheatsheet
    assert "yt-postmortem-pending" in cheatsheet
    assert "/analytics --flop" in cheatsheet
