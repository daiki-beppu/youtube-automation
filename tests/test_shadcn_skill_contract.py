"""公式 shadcn skill の導入・provenance・配布入口を固定する。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "shadcn"
SKILL_FILE = SKILL_DIR / "SKILL.md"
AGENTS_SKILLS = REPO_ROOT / ".agents" / "skills"
LOCK_FILE = REPO_ROOT / "skills-lock.json"
EXTENSIONS_GUIDE = REPO_ROOT / "extensions" / "CLAUDE.md"

EXPECTED_CORE_FILES = {
    "SKILL.md",
    "cli.md",
    "customization.md",
    "mcp.md",
    "registry.md",
    "rules/base-vs-radix.md",
    "rules/composition.md",
    "rules/forms.md",
    "rules/icons.md",
    "rules/styling.md",
}


def test_official_shadcn_skill_is_copied_without_symlinks() -> None:
    assert SKILL_DIR.is_dir()
    installed = {path.relative_to(SKILL_DIR).as_posix() for path in SKILL_DIR.rglob("*") if path.is_file()}
    assert EXPECTED_CORE_FILES <= installed
    assert not [path for path in SKILL_DIR.rglob("*") if path.is_symlink()]


def test_frontmatter_keeps_official_identity_and_strict_description() -> None:
    text = SKILL_FILE.read_text(encoding="utf-8")
    _, frontmatter, _ = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    assert metadata["name"] == "shadcn"
    description_line = next(line for line in frontmatter.splitlines() if line.startswith("description:"))
    assert description_line.startswith('description: "')


def test_installer_provenance_is_pinned_to_one_official_skill() -> None:
    lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    assert lock["version"] == 1
    assert set(lock["skills"]) == {"shadcn"}
    provenance = lock["skills"]["shadcn"]
    assert provenance["source"] == "shadcn/ui"
    assert provenance["sourceType"] == "github"
    assert provenance["skillPath"] == "skills/shadcn/SKILL.md"
    assert len(provenance["computedHash"]) == 64
    assert len(provenance["resolvedRevision"]) == 40


def test_codex_discovery_resolves_the_same_skill() -> None:
    assert AGENTS_SKILLS.is_symlink()
    assert AGENTS_SKILLS.readlink() == Path("../.claude/skills")
    assert (AGENTS_SKILLS / "shadcn" / "SKILL.md").resolve() == SKILL_FILE.resolve()


def test_extensions_guide_requires_official_docs_and_registry_diff_first() -> None:
    guide = EXTENSIONS_GUIDE.read_text(encoding="utf-8")
    for command in (
        "shadcn@latest info --json",
        "shadcn@latest docs <component>",
        "add <component> --dry-run",
        "add <component> --diff <file>",
    ):
        assert command in guide
