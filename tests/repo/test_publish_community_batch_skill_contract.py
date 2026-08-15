"""Contracts for ``/publish --community --batch`` (#3844)."""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.skills.inventory import SkillInventory

INVENTORY = SkillInventory(REPO_ROOT)
PUBLISH = INVENTORY.skill_directory("publish")


def _section(text: str, heading: str, next_heading: str) -> str:
    return text.split(heading, 1)[1].split(next_heading, 1)[0]


def test_batch_is_a_community_only_modifier() -> None:
    skill = (PUBLISH / "SKILL.md").read_text(encoding="utf-8")
    modes = _section(skill, "## モード判定", "## 修飾フラグ")
    modifiers = _section(skill, "## 修飾フラグ", "## 設定読み込みゲート")

    assert "--batch" not in modes
    assert "| `--batch` | `--community` の" in modifiers
    assert re.search(r"`--batch`.*`--community`.*エラー.*停止", modifiers, re.DOTALL)
    assert "--community --batch" in skill


def test_publish_owns_community_batch_generator_and_old_skill_is_absent() -> None:
    names = {path.name for path in INVENTORY.skill_directories()}
    community = (PUBLISH / "references" / "community.md").read_text(encoding="utf-8")
    generator = PUBLISH / "references" / "generate_batch.py"

    assert "community-draft" not in names
    assert generator.is_file()
    assert "--batch" in community
    assert "30-promo/community-posts.json" in community
    assert ".claude/skills/publish/references/generate_batch.py" in community


def test_authoring_guidance_points_to_publish_batch_modifier() -> None:
    guidance = (REPO_ROOT / "docs/skill-design/skill-authoring-guidelines.md").read_text(encoding="utf-8")

    assert "community-draft" not in guidance
    assert "publish" in guidance
    assert "`--batch`" in guidance
