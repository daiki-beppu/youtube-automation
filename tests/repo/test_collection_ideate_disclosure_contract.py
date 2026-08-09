"""段階開示後の collection-ideate 企画規則の所有契約。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "collection-ideate"
SKILL_MD = SKILL_DIR / "SKILL.md"
PLANNING_RULES_MD = SKILL_DIR / "references" / "planning-rules.md"
PREVIEW_CONTRACT_MD = SKILL_DIR / "references" / "preview-contract.md"

PLANNING_RULE_HEADINGS = {
    "ペルソナベース企画フレームワーク",
    "タイトルテンプレート",
    "差別化軸",
    "vote-log hook",
    "オブジェクトデザインルール",
    "オリジナリティ保証ルール",
    "第一ペルソナの企画バリエーション",
}
PREVIEW_CONTRACT_HEADINGS = {
    "Preview 設定",
    "候補 schema",
    "コスト計算契約",
    "セルフチェック契約",
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


def test_skill_dispatches_preview_contract_before_preview_steps() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    relative_reference = PREVIEW_CONTRACT_MD.relative_to(SKILL_DIR).as_posix()

    dispatch = skill.index(f"]({relative_reference})")
    first_preview_step = skill.index("**4-1:")

    assert PREVIEW_CONTRACT_MD.is_file()
    assert dispatch < first_preview_step


def test_preview_contract_sections_have_one_reference_owner() -> None:
    skill_headings = _headings(SKILL_MD.read_text(encoding="utf-8"))
    reference_headings = _headings(PREVIEW_CONTRACT_MD.read_text(encoding="utf-8"))

    assert PREVIEW_CONTRACT_HEADINGS <= reference_headings
    assert PREVIEW_CONTRACT_HEADINGS.isdisjoint(skill_headings)


def test_preview_contract_preserves_phase_4_1_prompt_semantics() -> None:
    contract = PREVIEW_CONTRACT_MD.read_text(encoding="utf-8")

    assert "英語 1 段落" in contract
    assert "誇張表現禁止" in contract
    assert "16:9 構図" in contract
    assert "テキスト除外" in contract


def test_preview_contract_dispatches_generation_mode_prompt_source() -> None:
    contract = PREVIEW_CONTRACT_MD.read_text(encoding="utf-8")

    single_step = contract.index("`generation_mode: single_step`")
    diff_template = contract.index("`diff_prompt_template`", single_step)
    other_modes = contract.index("それ以外の generation mode", diff_template)
    phase_4_1_prompt = contract.index("Phase 4-1 のプロンプト全文", other_modes)

    assert single_step < diff_template < other_modes < phase_4_1_prompt


def test_cost_approval_precedes_preview_side_effects() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    phase_4 = skill.index("### Phase 4:")

    approval = skill.index("confirm_cost", phase_4)
    session_creation = skill.index("mkdir -p", phase_4)
    image_generation = skill.index("yt-generate-image", phase_4)

    assert approval < session_creation < image_generation
