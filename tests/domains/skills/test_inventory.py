from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.domains.skills.inventory import (
    SkillInventory,
    extract_markdown_section,
    parse_frontmatter,
)


def _write_skill(root: Path, name: str, *, description: str = "説明") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "{description}"\n---\n\n## 本文\n\n{name}\n',
        encoding="utf-8",
    )
    return skill_dir


def test_repo_and_wheel_roots_produce_the_same_inventory(tmp_path: Path) -> None:
    # Given: repository layout and installed-wheel layout with the same skills
    repo_root = tmp_path / "repo"
    wheel_root = tmp_path / "wheel" / "_skills"
    for root in (repo_root / ".claude" / "skills", wheel_root):
        _write_skill(root, "alpha", description="shared")
        _write_skill(root, "beta", description="shared")

    # When: both supported roots are queried
    repo_inventory = SkillInventory(repo_root)
    wheel_inventory = SkillInventory(wheel_root)

    # Then: enumeration and parsing produce the same results
    assert [path.name for path in repo_inventory.skill_directories()] == ["alpha", "beta"]
    assert [path.name for path in wheel_inventory.skill_directories()] == ["alpha", "beta"]
    assert repo_inventory.frontmatter("alpha") == wheel_inventory.frontmatter("alpha")


def test_repository_root_resolves_claude_skills_and_excludes_worktree_store(tmp_path: Path) -> None:
    # Given: a repository skill and a skill-like file inside the linked-worktree store
    expected = _write_skill(tmp_path / ".claude" / "skills", "alpha")
    _write_skill(tmp_path / ".claude" / "worktrees" / "nested" / ".claude" / "skills", "shadow")
    _write_skill(tmp_path / ".worktrees" / "legacy" / ".claude" / "skills", "legacy-shadow")

    # When: the repository root is injected
    inventory = SkillInventory(tmp_path)

    # Then: only the canonical repository skill root is enumerated
    assert inventory.skills_root == tmp_path / ".claude" / "skills"
    assert inventory.skill_directories() == (expected,)


def test_direct_wheel_root_enumerates_skill_directories_in_name_order(tmp_path: Path) -> None:
    # Given: a wheel-derived _skills root
    wheel_root = tmp_path / "package" / "_skills"
    beta = _write_skill(wheel_root, "beta")
    alpha = _write_skill(wheel_root, "alpha")

    # When / Then: direct root injection produces a stable inventory
    assert SkillInventory(wheel_root).skill_directories() == (alpha, beta)


def test_frontmatter_parser_returns_strict_yaml_mapping() -> None:
    # Given: a valid SKILL.md document
    text = '---\nname: sample\ndescription: "sample: description"\n---\n\nBody\n'

    # When: frontmatter is parsed
    parsed = parse_frontmatter(text)

    # Then: YAML values are available without the document body
    assert parsed == {"name": "sample", "description": "sample: description"}


def test_markdown_section_stops_at_same_or_higher_heading() -> None:
    # Given: a section with a nested heading followed by a sibling section
    text = "# Title\n\n## Target\n\nfirst\n\n### Nested\n\nsecond\n\n## Next\n\nthird\n"

    # When: the target section is extracted
    section = extract_markdown_section(text, "## Target")

    # Then: nested content is included and the sibling section is excluded
    assert section == "\nfirst\n\n### Nested\n\nsecond\n\n"


def test_markdown_section_rejects_missing_heading() -> None:
    with pytest.raises(ValueError, match="セクションが見つかりません"):
        extract_markdown_section("## Present\n", "## Missing")


def test_reference_resolution_reports_existing_and_missing_files(tmp_path: Path) -> None:
    # Given: a skill with one reference file
    skill_dir = _write_skill(tmp_path / "_skills", "sample")
    reference = skill_dir / "references" / "details.md"
    reference.parent.mkdir()
    reference.write_text("details", encoding="utf-8")
    inventory = SkillInventory(tmp_path / "_skills")

    # When / Then: paths resolve from the skill directory and existence is explicit
    assert inventory.resolve_reference("sample", "references/details.md") == reference.resolve()
    assert inventory.reference_exists("sample", "references/details.md")
    assert not inventory.reference_exists("sample", "references/missing.md")
