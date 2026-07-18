"""analytics-analyze の登録転換分析指示を契約化する。"""

from __future__ import annotations

from pathlib import Path

SKILL_PATH = Path(".claude/skills/analytics-analyze/SKILL.md")


def test_skill_requires_subscription_conversion_analysis_with_aggregate_caveat() -> None:
    """スキルが両 JSON パス、比率、解釈上の制約を明記する。"""
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "登録を生む動画の型" in skill
    assert "strategic_analysis.subscriber_conversion_ranking" in skill
    assert "subscribers_gained ÷ views × 100" in skill
    assert "audience.by_subscribed_status" in skill
    assert "チャンネル全体集計" in skill
    assert "個別動画の転換原因とは断定しない" in skill
