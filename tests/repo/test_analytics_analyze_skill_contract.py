"""analytics の登録転換分析指示を契約化する。"""

from __future__ import annotations

from pathlib import Path

SKILL_PATH = Path(".claude/skills/analytics/references/analyze.md")


def test_skill_requires_subscription_conversion_analysis_with_aggregate_caveat() -> None:
    """スキルが両 JSON パス、比率、解釈上の制約を明記する。"""
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "登録を生む動画の型" in skill
    assert "strategic_analysis.subscriber_conversion_ranking" in skill
    assert "subscribers_gained ÷ views × 100" in skill
    assert "audience.by_subscribed_status" in skill
    assert "チャンネル全体集計" in skill
    assert "個別動画の転換原因とは断定しない" in skill


def test_vpd_commands_capture_one_snapshot_and_reuse_it_offline() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")

    rank_command = 'uv run yt-vpd-rank >"$vpd_ranking_path"'
    win_command = (
        "uv run yt-win-pattern \\\n"
        '  --ranking "$vpd_ranking_path" \\\n'
        '  --annotations "$visual_annotations_path" \\\n'
        '  >"$win_pattern_path"'
    )
    assert skill.count(rank_command) == 1
    assert skill.count(win_command) == 1
    assert skill.index(rank_command) < skill.index(win_command)
    assert "中間群や captured ranking 外の ID は入れない" in skill
    assert "観測不能は `null`" in skill
