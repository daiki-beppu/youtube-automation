from __future__ import annotations

import json
import re

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.analytics.truth_eye import PAIR_THRESHOLDS, VIEWPOINTS
from youtube_automation.domains.skills.inventory import SkillInventory

SKILL_DIR = REPO_ROOT / ".claude/skills/truth-eye"


def test_truth_eye_frontmatter_and_references_are_fixed():
    metadata = SkillInventory(REPO_ROOT / ".claude/skills").frontmatter("truth-eye")
    assert metadata["name"] == "truth-eye"
    assert metadata["purpose"] == "振り返る"
    assert "真実の目" in metadata["description"]
    assert {path.name for path in (SKILL_DIR / "references").glob("*.md")} == {
        "viewpoints.md",
        "pair-selection.md",
        "grilling.md",
        "sealed-analysis.md",
        "record-format.md",
    }


def test_truth_eye_viewpoint_reference_matches_python_constant():
    text = (SKILL_DIR / "references/viewpoints.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (V\d{2}) \| ([^|]+) \| (必須|任意) \|", text, re.MULTILINE)
    assert rows == [(item.id, item.name, "必須" if item.required else "任意") for item in VIEWPOINTS]


def test_truth_eye_threshold_reference_matches_python_constant():
    text = (SKILL_DIR / "references/pair-selection.md").read_text(encoding="utf-8")
    rows = dict(re.findall(r"^\| ([a-z0-9_]+) \| ([0-9]+) \|$", text, re.MULTILINE))
    assert rows == {
        "gap_days_1": str(PAIR_THRESHOLDS.gap_days[0]),
        "gap_days_2": str(PAIR_THRESHOLDS.gap_days[1]),
        "gap_days_3": str(PAIR_THRESHOLDS.gap_days[2]),
        "maturity_days": str(PAIR_THRESHOLDS.maturity_days),
        "min_ratio": str(int(PAIR_THRESHOLDS.min_ratio)),
        "min_loser_views": str(PAIR_THRESHOLDS.min_loser_views),
        "min_pool_size": str(PAIR_THRESHOLDS.min_pool_size),
    }


def test_truth_eye_registration_and_cli_workflow_contract():
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    for subcommand in ("pair", "seal", "verify", "status"):
        assert f"yt-truth-eye {subcommand}" in skill
    assert len(skill.splitlines()) <= 400
    assert "docs/skill-design/" not in skill
    assert re.search(r"\bA\s*/\s*B\b", skill) is None
    features = (REPO_ROOT / "docs/features.md").read_text(encoding="utf-8")
    assert "| /truth-eye |" in features
    artifacts = json.loads(
        (REPO_ROOT / "src/youtube_automation/domains/documents/operational-artifacts.json").read_text(encoding="utf-8")
    )
    assert {
        "path": "docs/benchmarks/training/*.md",
        "owner": "truth-eye",
        "reason": "人間が記入する訓練記録と、その封印分析（AI 生成・sha256 封印）",
    } in artifacts["allowlists"]["hand_written_inputs"]
