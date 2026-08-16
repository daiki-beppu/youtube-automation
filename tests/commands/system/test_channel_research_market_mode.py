"""Contracts for integrating market analysis into /channel-research (#3817)."""

from pathlib import Path

import yaml

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system.skills_sync import bundled_skill_names

ROOT = REPO_ROOT
CHANNEL_STRATEGY = ROOT / ".claude/skills/channel-strategy/SKILL.md"
CHANNEL_RESEARCH = ROOT / ".claude/skills/channel-research/SKILL.md"
MARKET_MODE = ROOT / ".claude/skills/channel-research/references/market.md"
VOICE_MODE = ROOT / ".claude/skills/channel-research/references/voice.md"
THUMBNAIL_MODE = ROOT / ".claude/skills/channel-research/references/thumbnail.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_channel_research_owns_market_and_legacy_skills_are_not_distributed() -> None:
    assert (ROOT / ".claude/skills/channel-research").is_dir()
    assert MARKET_MODE.is_file()
    assert "channel-research" in bundled_skill_names()
    assert "market-research" not in bundled_skill_names()


def test_channel_research_owns_voice_and_legacy_skill_is_not_distributed() -> None:
    assert VOICE_MODE.is_file()
    assert "viewer-voice" not in bundled_skill_names()
    assert not (ROOT / ".claude/skills/viewer-voice").exists()


def test_channel_research_owns_thumbnail_research_and_legacy_skill_is_not_distributed() -> None:
    assert THUMBNAIL_MODE.is_file()
    assert "thumbnail-research" not in bundled_skill_names()
    assert not (ROOT / ".claude/skills/thumbnail-research").exists()


def test_channel_strategy_owns_direction_without_market_analysis() -> None:
    skill = _read(CHANNEL_STRATEGY)
    frontmatter = yaml.safe_load(skill.split("---", 2)[1])
    description = frontmatter["description"]

    for keyword in ("競合分析", "チャンネルリサーチ", "TTP 対象抽出"):
        assert keyword not in description
    assert "references/direction.md" in skill
    assert "references/analysis-mode.md" not in skill


def test_market_mode_preserves_both_branches_inputs_gates_and_outputs() -> None:
    mode = _read(MARKET_MODE)

    for step in range(8):
        assert f"Step {step}" in mode
    for contract in (
        "data/benchmark_*.json",
        "data/comments_*.json",
        "docs/benchmarks/benchmark-report.json",
        "Subagent 委譲ゲート",
        "停止する fail",
        "許容する fail",
        "具体 ⇄ 抽象の往復を最低 3 回",
        "docs/channel-research.json",
        "docs/research/market-<YYYY-MM-DD>.json",
        "market-comparison",
        "collected-analysis",
        ".claude/skills/channel-strategy/references/desire-vocabulary.md",
    ):
        assert contract in mode


def test_channel_research_exposes_five_modes_without_splitting_market_depth() -> None:
    skill = _read(CHANNEL_RESEARCH)
    frontmatter = yaml.safe_load(skill.split("---", 2)[1])
    paths = (
        ".claude/skills/channel-research/references/thumbnail.md",
        ".claude/skills/channel-research/references/discover.md",
    )
    assert all(
        flag in frontmatter["description"]
        for flag in ("--benchmark", "--discover", "--market", "--voice", "--thumbnail")
    )
    mode_table = skill.split("| mode | 読む reference |", 1)[1].split("## 共通前提", 1)[0]
    assert [line.split("|", 2)[1].strip() for line in mode_table.splitlines() if line.startswith("| `--")] == [
        "`--benchmark`",
        "`--discover`",
        "`--market`",
        "`--voice`",
        "`--thumbnail`",
    ]
    for relative in paths:
        text = _read(ROOT / relative)
        assert "/channel-research --market" in text


def test_feature_catalog_lists_channel_research_as_market_owner() -> None:
    features = _read(ROOT / "docs/features.md")
    assert "| /channel-research |" in features
    assert "`--market`" in features
    assert "`--voice`" in features
    assert "`--thumbnail`" in features


def test_comment_collector_has_one_skill_reference_owner() -> None:
    matches = list((ROOT / ".claude/skills").glob("*/references/fetch_benchmark_comments.py"))

    assert matches == [ROOT / ".claude/skills/channel-research/references/fetch_benchmark_comments.py"]
