"""利用者向け workflow skill surface の契約。"""

from __future__ import annotations

import re
from pathlib import Path

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.skills.inventory import SkillInventory

INVENTORY = SkillInventory(REPO_ROOT)


def _description(skill: str) -> str:
    metadata = INVENTORY.frontmatter(skill)
    assert isinstance(metadata, dict)
    description = metadata.get("description")
    assert isinstance(description, str)
    return description


def _section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(heading)}\n(?P<body>.*?)(?=^##\s|\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert match is not None, heading
    return match.group("body")


def test_public_workflow_skill_directories_are_fixed_to_three_routes() -> None:
    workflow_skills = {path.name for path in INVENTORY.skill_directories() if path.name.startswith("wf-")}

    assert workflow_skills == {"wf-new", "wf-next", "wf-status"}


def test_wf_new_owns_absorbed_ideation_contract() -> None:
    skill_names = {path.name for path in INVENTORY.skill_directories()}
    ideate_reference = INVENTORY.resolve_reference("wf-new", "references/ideate.md")
    wf_new = (INVENTORY.skill_directory("wf-new") / "SKILL.md").read_text(encoding="utf-8")

    assert "collection-ideate" not in skill_names
    assert ideate_reference.is_file()
    assert "references/ideate.md" in wf_new


def test_public_route_guidance_exposes_only_workflow_surface() -> None:
    cheatsheet_flow = _section(
        REPO_ROOT / "docs" / "workflow-cheatsheet.md",
        "## いまどの skill を呼ぶ？（判定フロー）",
    )
    trigger_list = _section(
        REPO_ROOT / ".claude" / "CLAUDE.template.md",
        "## 4. スキルの選び方",
    )

    assert "/collection-ideate" not in cheatsheet_flow
    assert "/collection-ideate" not in trigger_list
    onboarding = (REPO_ROOT / "ONBOARDING.md").read_text(encoding="utf-8")
    assert "/collection-ideate" not in onboarding
    for route in ("/wf-new", "/wf-next", "/wf-status"):
        assert route in cheatsheet_flow
        assert route in trigger_list

    features = (REPO_ROOT / "docs" / "features.md").read_text(encoding="utf-8")
    assert "| /collection-ideate |" not in features


def test_wf_new_description_exposes_all_exclusive_modes() -> None:
    description = _description("wf-new")

    for mode in ("--auto", "--batch", "--schedule"):
        assert mode in description
    assert "--ideate" not in description
