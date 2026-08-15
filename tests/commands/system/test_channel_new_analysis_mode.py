"""Contracts for integrating /channel-research into /channel-new (#2027)."""

from pathlib import Path

import yaml

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system.skills_sync import bundled_skill_names

ROOT = REPO_ROOT
CHANNEL_NEW = ROOT / ".claude/skills/channel-new/SKILL.md"
ANALYSIS_MODE = ROOT / ".claude/skills/channel-new/references/analysis-mode.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_channel_research_is_reintroduced_without_replacing_analysis_mode() -> None:
    assert (ROOT / ".claude/skills/channel-research").is_dir()
    assert ANALYSIS_MODE.is_file()
    assert "channel-research" in bundled_skill_names()
    assert "benchmark" not in bundled_skill_names()


def test_channel_new_routes_analysis_keywords_to_residual_mode() -> None:
    skill = _read(CHANNEL_NEW)
    frontmatter = yaml.safe_load(skill.split("---", 2)[1])
    description = frontmatter["description"]

    assert "2 つの mode" in skill
    assert "2. **分析モード**" in skill
    for keyword in ("競合分析", "チャンネルリサーチ", "TTP 対象抽出"):
        assert keyword in description
        assert keyword in skill
    assert "分析モード" in skill
    assert "references/analysis-mode.md" in skill
    assert "実行前に必ず" in skill
    assert "`/channel-research` は廃止しない" not in skill
    first_60_lines = "\n".join(skill.splitlines()[:60])
    assert "Hard Gates / 完了条件（分析モード）" in first_60_lines
    assert "references/analysis-mode.md" in first_60_lines
    assert "分析モードは除く" in skill
    assert "収集済みローカルデータだけを扱い" in skill


def test_analysis_mode_preserves_inputs_gates_delegation_and_outputs() -> None:
    mode = _read(ANALYSIS_MODE)

    for step in range(8):
        assert f"Step {step}" in mode
    for contract in (
        "data/benchmark_*.json",
        "data/comments_*.json",
        "docs/benchmarks/*.md",
        "Subagent 委譲ゲート",
        "停止する fail",
        "許容する fail",
        "具体 ⇄ 抽象の往復を最低 3 回",
        "docs/channel-research.md",
        "docs/benchmarks/thumbnail-text-profile.md",
        ".claude/skills/channel-new/references/desire-vocabulary.md",
    ):
        assert contract in mode


def test_sibling_routes_point_to_channel_new_analysis_mode() -> None:
    paths = (
        ".claude/skills/channel-research/SKILL.md",
        ".claude/skills/thumbnail-research/SKILL.md",
        ".claude/skills/channel-research/references/discover.md",
        ".claude/skills/market-research/SKILL.md",
    )
    for relative in paths:
        text = _read(ROOT / relative)
        assert "/channel-new" in text
        assert "分析モード" in text
        assert "/channel-research --benchmark" in text or relative.endswith("channel-research/SKILL.md")


def test_feature_catalog_lists_channel_research_and_keeps_analysis_mode() -> None:
    features = _read(ROOT / "docs/features.md")
    assert "| /channel-research |" in features
    assert "/channel-new" in features and "分析モード" in features
