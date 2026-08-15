"""`/automation --update` の統合インターフェース契約。"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

from tests.helpers.paths import REPO_ROOT, WORKTREE_STORE_PREFIXES, is_inside_worktree_store
from youtube_automation.commands.system.skills_sync._ops import _KNOWN_REMOVED_SKILL_NAMES
from youtube_automation.domains.skills.inventory import SkillInventory, parse_frontmatter

SKILL_INVENTORY = SkillInventory(REPO_ROOT)
SKILL_DIR = SKILL_INVENTORY.skill_directory("automation")
LEGACY_SKILL_NAME = "automation" + "-update"
_REPOSITORY_SCAN_EXCLUDED_DIRS = {".git", ".venv", ".direnv", "dist"}


def _repository_files(root: Path) -> Iterator[Path]:
    worktree_stores = tuple(
        store for prefix in WORKTREE_STORE_PREFIXES if is_inside_worktree_store(store := root.joinpath(*prefix), root)
    )
    for path in root.rglob("*"):
        if any(path.is_relative_to(store) for store in worktree_stores):
            continue
        if not path.is_file() or _REPOSITORY_SCAN_EXCLUDED_DIRS.intersection(path.parts):
            continue
        yield path


def test_automation_exposes_update_as_an_explicit_mode() -> None:
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(skill)

    assert isinstance(frontmatter, dict)
    assert frontmatter["name"] == "automation"
    assert "--update" in frontmatter["description"]
    assert LEGACY_SKILL_NAME in frontmatter["description"]
    assert "空または空白だけ" in skill and "停止" in skill
    assert "2 個以上なら" in skill and "排他違反" in skill
    assert (SKILL_DIR / "references" / "update.md").is_file()


def test_automation_routes_explicit_and_natural_language_questions() -> None:
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(skill)

    assert isinstance(frontmatter, dict)
    assert "--question" in frontmatter["description"]
    assert "`--question` | `references/question.md`" in skill
    assert "排他フラグなし" in skill and "question mode" in skill
    assert "空白" in skill and "停止" in skill
    assert "--update" in skill and "--question" in skill and "排他違反" in skill


def test_question_mode_declares_local_first_read_only_fallback_contract() -> None:
    question = (SKILL_DIR / "references" / "question.md").read_text(encoding="utf-8")

    local_source = question.index("## 配布物ローカル")
    upstream_source = question.index("## upstream GitHub fallback")
    assert local_source < upstream_source
    assert "UPSTREAM_REPO" in question
    assert "install 済み version" in question
    assert "/automation --update" in question
    assert "git 操作" in question and "yt-skills sync" in question
    assert "issue 作成" in question and "コメント" in question
    assert "/skill-feedback" in question


def test_legacy_skill_is_prunable_and_absent_from_the_catalog() -> None:
    assert LEGACY_SKILL_NAME in _KNOWN_REMOVED_SKILL_NAMES
    assert not os.path.lexists(REPO_ROOT / ".claude" / "skills" / LEGACY_SKILL_NAME)

    skill_names = {path.name for path in SKILL_INVENTORY.skill_directories()}
    assert "automation" in skill_names
    assert LEGACY_SKILL_NAME not in skill_names


def test_repository_has_no_legacy_skill_calls_or_paths() -> None:
    legacy_call = re.compile(rf"(?<![A-Za-z0-9_.-])/{re.escape(LEGACY_SKILL_NAME)}\b")
    legacy_path = f".claude/skills/{LEGACY_SKILL_NAME}"
    offenders: list[str] = []

    for path in _repository_files(REPO_ROOT):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if legacy_call.search(text) or legacy_path in text:
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []
