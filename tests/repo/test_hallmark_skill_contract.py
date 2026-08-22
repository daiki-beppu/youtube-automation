"""公式 Hallmark skill の導入・provenance・開発専用境界を固定する。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system.skills_sync import _DEV_ONLY_SKILL_NAMES

SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "hallmark"
SKILL_FILE = SKILL_DIR / "SKILL.md"
AGENTS_SKILLS = REPO_ROOT / ".agents" / "skills"
LOCK_FILE = REPO_ROOT / "skills-lock.json"


def test_official_hallmark_skill_and_references_are_copied_without_symlinks() -> None:
    assert SKILL_DIR.is_dir()
    assert SKILL_FILE.is_file()
    assert (SKILL_DIR / "references" / "contract.md").is_file()
    assert (SKILL_DIR / "references" / "verbs" / "audit.md").is_file()
    assert not [path for path in SKILL_DIR.rglob("*") if path.is_symlink()]


def test_frontmatter_preserves_upstream_identity_and_repository_contract() -> None:
    text = SKILL_FILE.read_text(encoding="utf-8")
    _, frontmatter, _ = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)

    assert metadata["name"] == "hallmark"
    assert metadata["version"] == "1.1.0"
    assert metadata["purpose"]
    description_line = next(line for line in frontmatter.splitlines() if line.startswith("description:"))
    assert description_line.startswith('description: "')


def test_installer_provenance_is_pinned() -> None:
    provenance = json.loads(LOCK_FILE.read_text(encoding="utf-8"))["skills"]["hallmark"]

    assert provenance["source"] == "nutlope/hallmark"
    assert provenance["sourceType"] == "github"
    assert provenance["skillPath"] == "skills/hallmark/SKILL.md"
    assert provenance["version"] == "1.1.0"
    assert provenance["license"] == "MIT"
    assert len(provenance["computedHash"]) == 64
    assert len(provenance["resolvedRevision"]) == 40


def test_claude_and_codex_resolve_the_same_dev_only_skill() -> None:
    assert AGENTS_SKILLS.is_symlink()
    assert AGENTS_SKILLS.readlink() == Path("../.claude/skills")
    assert (AGENTS_SKILLS / "hallmark" / "SKILL.md").resolve() == SKILL_FILE.resolve()
    assert "hallmark" in _DEV_ONLY_SKILL_NAMES
