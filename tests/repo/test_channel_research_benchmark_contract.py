"""Contracts for migrating ``/benchmark`` into ``/channel-research`` (#3815)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml

from tests.helpers.paths import REPO_ROOT
from youtube_automation.configuration.skills import skill_config_default_relative_path
from youtube_automation.domains.skills.inventory import SkillInventory

INVENTORY = SkillInventory(REPO_ROOT)
SKILL_DIR = INVENTORY.skill_directory("channel-research")


def test_channel_research_replaces_legacy_skills_and_exposes_two_modes() -> None:
    assert SKILL_DIR.is_dir()
    assert not os.path.lexists(INVENTORY.skills_root / "benchmark")
    assert not os.path.lexists(INVENTORY.skills_root / "discover-competitors")

    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = INVENTORY.frontmatter("channel-research")
    assert frontmatter["name"] == "channel-research"
    assert frontmatter["purpose"] == "調べる"
    assert "--benchmark" in frontmatter["description"]
    assert "$ARGUMENTS" in skill
    assert "2 個以上" in skill
    assert "0 個" in skill and "chain manifest" in skill
    assert "references/benchmark.md" in skill
    assert "references/discover.md" in skill


def test_chain_manifest_has_four_steps_and_complete_schema() -> None:
    manifest = json.loads((SKILL_DIR / "references/channel-research-chain-manifest.json").read_text())
    assert manifest["chainId"] == "channel-research"
    assert [step["id"] for step in manifest["steps"]] == ["benchmark", "discover", "voice", "market"]
    assert "thumbnail" not in {step["id"] for step in manifest["steps"]}
    step = manifest["steps"][0]
    assert set(step) == {
        "id",
        "skill",
        "prerequisiteArtifacts",
        "outputArtifacts",
        "approvalGate",
        "idempotency",
    }
    assert step["skill"] == "channel-research"
    assert step["outputArtifacts"] == [
        "data/benchmark_*.json",
        "docs/benchmarks/benchmark-report.json",
        "docs/benchmarks/benchmark-report.html",
    ]
    assert step["approvalGate"]["skip"] is True
    assert step["idempotency"]["script"] == "references/channel-research-chain-state.py"
    discover = manifest["steps"][1]
    assert discover["skill"] == "channel-research"
    assert discover["prerequisiteArtifacts"] == [
        "docs/benchmarks/benchmark-report.json",
        "docs/benchmarks/benchmark-report.html",
    ]
    assert discover["outputArtifacts"] == ["research/*-discovery.md", "research/*-discovery.csv"]
    voice = manifest["steps"][2]
    assert voice["prerequisiteArtifacts"] == [
        "data/benchmark_*.json",
        "docs/benchmarks/benchmark-report.json",
        "docs/benchmarks/benchmark-report.html",
        "research/*-discovery.md",
        "research/*-discovery.csv",
    ]
    assert voice["outputArtifacts"] == [
        "data/comments_*.json",
        "docs/plans/viewer-voice-analysis.json",
        "docs/plans/viewer-voice-analysis.html",
    ]
    market = manifest["steps"][3]
    assert market["prerequisiteArtifacts"] == []
    assert market["outputArtifacts"] == [
        "docs/research/market-*.json",
        "docs/research/market-*.html",
        "docs/channel-research.json",
        "docs/channel-research.html",
    ]


def test_benchmark_collector_has_one_skill_reference_owner() -> None:
    matches = [
        path
        for skill_dir in INVENTORY.skill_directories()
        if (path := skill_dir / "references" / "benchmark_collector.py").exists() or path.is_symlink()
    ]
    assert matches == [SKILL_DIR / "references/benchmark_collector.py"]
    collector = matches[0]
    assert collector.is_symlink()
    assert os.readlink(collector) == "../../../../src/youtube_automation/commands/analytics/benchmark_collector.py"


def test_benchmark_config_key_keeps_legacy_override_and_uses_moved_default() -> None:
    assert skill_config_default_relative_path("benchmark") == Path("channel-research/config.default.yaml")
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert 'load_skill_config("benchmark")' in skill
    assert "config/skills/benchmark.yaml" in skill
    assert "`config/skills/channel-research.yaml` は先行作成しない" in skill
    assert "yt-skills migrate-config" in skill


def test_discover_config_key_keeps_legacy_override_and_uses_namespaced_default() -> None:
    assert skill_config_default_relative_path("discover-competitors") == Path("channel-research/config.default.yaml")
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert 'load_skill_config("discover-competitors")' in skill
    assert "config/skills/discover-competitors.yaml" in skill
    defaults = yaml.safe_load((SKILL_DIR / "config.default.yaml").read_text(encoding="utf-8"))
    assert set(defaults) == {"benchmark", "discover"}
    assert defaults["benchmark"]["freshness_days"] == 3
    assert defaults["discover"]["search"]["top"] == 20


def test_active_skills_no_longer_route_to_legacy_benchmark_command() -> None:
    offenders: list[str] = []
    for skill_dir in INVENTORY.skill_directories():
        for path in skill_dir.rglob("*.md"):
            if re.search(r"(?<![A-Za-z0-9_.-])/benchmark\b", path.read_text(encoding="utf-8")):
                offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert offenders == []
