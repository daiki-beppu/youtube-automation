"""段階開示後の collection-ideate 企画規則の所有契約。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "collection-ideate"
SKILL_MD = SKILL_DIR / "SKILL.md"
PLANNING_RULES_MD = SKILL_DIR / "references" / "planning-rules.md"

PLANNING_RULE_HEADINGS = {
    "ペルソナベース企画フレームワーク",
    "タイトルテンプレート",
    "差別化軸",
    "vote-log hook",
    "オブジェクトデザインルール",
    "オリジナリティ保証ルール",
    "第一ペルソナの企画バリエーション",
}


def _headings(markdown: str) -> set[str]:
    headings: set[str] = set()
    for match in re.finditer(r"^#{2,4}\s+(.+?)\s*$", markdown, re.MULTILINE):
        heading = re.sub(r"\s*\([^)]*\)\s*$", "", match.group(1))
        headings.add(re.sub(r"\s*（[^）]*）\s*$", "", heading))
    return headings


def test_skill_dispatches_planning_rules_to_distributed_reference() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    relative_reference = PLANNING_RULES_MD.relative_to(SKILL_DIR).as_posix()

    assert f"]({relative_reference})" in skill
    assert PLANNING_RULES_MD.is_file()


def test_planning_rule_sections_have_one_reference_owner() -> None:
    skill_headings = _headings(SKILL_MD.read_text(encoding="utf-8"))
    reference_headings = _headings(PLANNING_RULES_MD.read_text(encoding="utf-8"))

    assert PLANNING_RULE_HEADINGS <= reference_headings
    assert PLANNING_RULE_HEADINGS.isdisjoint(skill_headings)


def test_skill_keeps_phase_order_and_approval_boundary() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")

    dispatch = skill.index("](references/planning-rules.md)")
    phase_2 = skill.index("### Phase 2:")
    phase_3 = skill.index("### Phase 3:")
    phase_4 = skill.index("### Phase 4:")
    approval = skill.index("confirm_cost", phase_4)

    assert dispatch < phase_2 < phase_3 < phase_4 < approval
