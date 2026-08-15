from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.domains.skills.inventory import (
    SkillInventory,
    extract_markdown_section,
    lint_skill,
    parse_frontmatter,
)


def _write_skill(root: Path, name: str, *, description: str = "説明") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "{description}"\npurpose: 作る\n---\n\n## 本文\n\n{name}\n',
        encoding="utf-8",
    )
    return skill_dir


def _write_flag_skill(root: Path, name: str, description: str, body: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "{description}"\npurpose: 作る\n---\n\n{body}',
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


def test_lint_skill_reports_missing_flag_tables(tmp_path: Path) -> None:
    skill_dir = _write_flag_skill(tmp_path, "sample", "Use --fast", "## 本文\n")

    violations = lint_skill(skill_dir)

    assert any("モード判定" in violation and "修飾フラグ" in violation for violation in violations)


def test_lint_skill_reports_description_flag_missing_from_tables(tmp_path: Path) -> None:
    skill_dir = _write_flag_skill(
        tmp_path,
        "sample",
        "Use --fast",
        """## 修飾フラグ

| modifier | 効果 |
|---|---|
| `--safe` | 安全に実行する |
""",
    )

    violations = lint_skill(skill_dir)

    assert any("--fast" in violation and "未登録" in violation for violation in violations)


def test_lint_skill_reports_flag_registered_as_mode_and_modifier(tmp_path: Path) -> None:
    skill_dir = _write_flag_skill(
        tmp_path,
        "sample",
        "Use --fast",
        """## モード判定

2 個以上の同時指定なら停止する。

| mode | 読む reference |
|---|---|
| `--fast` | `references/fast.md` |

## 修飾フラグ

| modifier | 効果 |
|---|---|
| `--fast` | 高速化する |
""",
    )

    violations = lint_skill(skill_dir)

    assert any("--fast" in violation and "重複所属" in violation for violation in violations)


@pytest.mark.parametrize("mode_count, violates", [(5, False), (6, True)])
def test_lint_skill_enforces_five_mode_limit(tmp_path: Path, mode_count: int, violates: bool) -> None:
    flags = [f"--mode-{index}" for index in range(mode_count)]
    rows = "\n".join(f"| `{flag}` | `references/{flag[2:]}.md` |" for flag in flags)
    skill_dir = _write_flag_skill(
        tmp_path,
        "sample",
        "Use " + " / ".join(flags),
        f"""## モード判定

2 個以上の同時指定なら停止する。

| mode | 読む reference |
|---|---|
{rows}
""",
    )

    violations = lint_skill(skill_dir)

    assert any("mode は 5 個以下" in violation for violation in violations) is violates


def test_lint_skill_does_not_limit_modifier_count(tmp_path: Path) -> None:
    flags = [f"--modifier-{index}" for index in range(6)]
    rows = "\n".join(f"| `{flag}` | 調整 {flag[11:]} |" for flag in flags)
    skill_dir = _write_flag_skill(
        tmp_path,
        "sample",
        "Use " + " / ".join(flags),
        f"""## 修飾フラグ

| modifier | 効果 |
|---|---|
{rows}
""",
    )

    assert lint_skill(skill_dir) == []


def test_lint_skill_ignores_flags_with_value_placeholders(tmp_path: Path) -> None:
    skill_dir = _write_flag_skill(tmp_path, "sample", "Use --since <N>", "## 本文\n")

    assert lint_skill(skill_dir) == []


def test_lint_skill_requires_exclusive_mode_instruction(tmp_path: Path) -> None:
    skill_dir = _write_flag_skill(
        tmp_path,
        "sample",
        "Use --fast",
        """## モード判定

| mode | 読む reference |
|---|---|
| `--fast` | `references/fast.md` |
""",
    )

    violations = lint_skill(skill_dir)

    assert any("2 個以上" in violation and "停止" in violation for violation in violations)


def test_lint_skill_reports_missing_mode_reference(tmp_path: Path) -> None:
    skill_dir = _write_flag_skill(
        tmp_path,
        "sample",
        "Use --fast",
        """## モード判定

2 個以上の同時指定なら停止する。

| mode | 読む reference |
|---|---|
| `--fast` | `references/fast.md` |
""",
    )

    violations = lint_skill(skill_dir)

    assert "--fast の reference が見つかりません: references/fast.md" in violations


def test_lint_skill_reports_absolute_mode_reference(tmp_path: Path) -> None:
    skill_dir = _write_flag_skill(
        tmp_path,
        "sample",
        "Use --fast",
        """## モード判定

2 個以上の同時指定なら停止する。

| mode | 読む reference |
|---|---|
| `--fast` | `/tmp/fast.md` |
""",
    )

    violations = lint_skill(skill_dir)

    assert any("--fast" in violation and "相対パス" in violation for violation in violations)


def test_lint_skill_reports_mode_reference_name_mismatch(tmp_path: Path) -> None:
    skill_dir = _write_flag_skill(
        tmp_path,
        "sample",
        "Use --fast",
        """## モード判定

2 個以上の同時指定なら停止する。

| mode | 読む reference |
|---|---|
| `--fast` | `references/details.md` |
""",
    )
    reference = skill_dir / "references" / "details.md"
    reference.parent.mkdir()
    reference.write_text("details", encoding="utf-8")

    violations = lint_skill(skill_dir)

    assert any(
        "--fast" in violation and "references/fast.md" in violation and "一致" in violation for violation in violations
    )


def test_lint_skill_reports_shared_mode_reference(tmp_path: Path) -> None:
    skill_dir = _write_flag_skill(
        tmp_path,
        "sample",
        "Use --fast / --safe",
        """## モード判定

2 個以上の同時指定なら停止する。

| mode | 読む reference |
|---|---|
| `--fast` | `references/fast.md` |
| `--safe` | `references/fast.md` |
""",
    )
    reference = skill_dir / "references" / "fast.md"
    reference.parent.mkdir()
    reference.write_text("details", encoding="utf-8")

    violations = lint_skill(skill_dir)

    assert any("--fast" in violation and "--safe" in violation and "共有" in violation for violation in violations)


def test_lint_skill_accepts_one_existing_named_reference_per_mode(tmp_path: Path) -> None:
    skill_dir = _write_flag_skill(
        tmp_path,
        "sample",
        "Use --fast / --safe",
        """## モード判定

2 個以上の同時指定なら停止する。

| mode | 読む reference |
|---|---|
| `--fast` | `references/fast.md` |
| `--safe` | `references/safe.md` |
""",
    )
    references = skill_dir / "references"
    references.mkdir()
    (references / "fast.md").write_text("fast", encoding="utf-8")
    (references / "safe.md").write_text("safe", encoding="utf-8")

    assert lint_skill(skill_dir) == []
