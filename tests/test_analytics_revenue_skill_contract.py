"""収益収集・RPM 分析の skill 契約。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_analytics_collect_documents_graceful_monetary_skip():
    skill = (ROOT / ".claude/skills/analytics-collect/SKILL.md").read_text()

    assert "estimatedRevenue" in skill
    assert 'revenue_analytics.status: "unavailable"' in skill
    assert "既存メトリクスの収集は継続" in skill


def test_analytics_analyze_requires_weighted_theme_and_collection_rpm():
    skill = (ROOT / ".claude/skills/analytics-analyze/SKILL.md").read_text()

    assert "テーマ別・コレクション別" in skill
    assert "収益合計 / 再生合計 * 1000" in skill
    assert "動画別 RPM の単純平均は使わない" in skill
    assert "収益・RPM 分析" in skill
