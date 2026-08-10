"""`/analytics` の統合インターフェース契約テスト。"""

from __future__ import annotations

import os

import yaml

from tests.helpers.paths import REPO_ROOT

SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "analytics"
LEGACY_MODES = ("collect", "analyze", "report", "run")


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
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or {".git", ".venv", ".direnv"}.intersection(path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(token in text for token in (*legacy_commands, *legacy_skill_paths, *legacy_config_paths)):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []
