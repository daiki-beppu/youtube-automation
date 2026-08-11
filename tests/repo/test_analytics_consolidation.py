"""`/analytics` の統合インターフェース契約テスト。"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import yaml

from tests.helpers.paths import REPO_ROOT, WORKTREE_STORE_PREFIXES, is_inside_worktree_store

SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "analytics"
LEGACY_MODES = ("collect", "analyze", "report", "run")
_REPOSITORY_SCAN_EXCLUDED_DIRS = {".git", ".venv", ".direnv"}


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


def test_repository_scan_keeps_repo_files_and_skips_worktree_stores(tmp_path: Path) -> None:
    repo_file = tmp_path / "tests" / "contract.py"
    repo_file.parent.mkdir()
    repo_file.write_text("repo", encoding="utf-8")

    worktree_files = {
        tmp_path / ".worktrees" / "legacy" / "contract.py",
        tmp_path / ".claude" / "worktrees" / "current" / "contract.py",
    }
    for path in worktree_files:
        path.parent.mkdir(parents=True)
        path.write_text("worktree", encoding="utf-8")

    scanned = set(_repository_files(tmp_path))

    assert repo_file in scanned
    assert scanned.isdisjoint(worktree_files)


def test_analytics_exposes_full_chain_and_exclusive_modes() -> None:
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(skill.split("---", 2)[1])

    assert frontmatter["name"] == "analytics"
    assert all(f"--{mode}" in frontmatter["description"] for mode in LEGACY_MODES[:3])
    assert "排他" in skill
    assert "collect → analyze → report" in skill


def test_analytics_uses_one_merged_skill_config() -> None:
    config = yaml.safe_load((SKILL_DIR / "config.default.yaml").read_text(encoding="utf-8"))

    assert config["freshness_minutes"] == 30
    assert config["html"]["kpi_cards"]
    assert config["theme"]["colors"]["chart_palette"]


def test_legacy_analytics_entrypoints_and_paths_are_removed() -> None:
    legacy_names = tuple(f"analytics-{mode}" for mode in LEGACY_MODES)
    for name in legacy_names:
        assert not os.path.lexists(REPO_ROOT / ".claude" / "skills" / name)

    legacy_commands = tuple(f"/{name}" for name in legacy_names)
    legacy_skill_paths = tuple(f".claude/skills/{name}/" for name in legacy_names)
    legacy_config_paths = tuple(f"config/skills/{name}.yaml" for name in legacy_names)
    offenders: list[str] = []
    for path in _repository_files(REPO_ROOT):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(token in text for token in (*legacy_commands, *legacy_skill_paths, *legacy_config_paths)):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []
