"""SKILL.md frontmatter が strict YAML (PyYAML safe_load) で安全に読めることを検証する (Issue #652)。

description 値内の `: ` (コロン+スペース) は strict YAML ではマッピング区切りと
誤解釈されパースが破綻する。全 skill の frontmatter を double-quoted string に統一し、
将来 strict YAML パーサで読む経路が追加されても壊れないことを保証する。

検証ロジックの単一ソースは `domains.skills.inventory` にあり、本テストはそれを全
skill に適用する回帰テスト (Issue #2096)。判定基準を変える場合は domain 側を修正すること。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system import skills_sync
from youtube_automation.domains.skills.inventory import lint_frontmatter_text, lint_skill

# リポジトリルート (tests/ の親)
_REPO_ROOT = REPO_ROOT
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"

_SKILL_DIRS = sorted(p.parent for p in _SKILLS_DIR.glob("*/SKILL.md"))


def test_command_adapter_reexports_domain_lint() -> None:
    assert skills_sync.lint_skill is lint_skill


def test_skill_files_discovered() -> None:
    # Given: .claude/skills 配下の SKILL.md
    # Then: 1 件以上見つかる (glob が空でないことを保証)
    assert _SKILL_DIRS, f"SKILL.md が見つかりません: {_SKILLS_DIR}"


@pytest.mark.parametrize("skill_dir", _SKILL_DIRS, ids=lambda p: p.name)
def test_frontmatter_passes_lint(skill_dir: Path) -> None:
    # Given: skill ディレクトリ
    # When: yt-skills lint と同一の frontmatter 検証ロジックを適用する
    violations = lint_frontmatter_text((skill_dir / "SKILL.md").read_text(encoding="utf-8"))

    # Then: 違反ゼロ (strict YAML パース / name・description 非空 / double-quote)
    assert not violations, f"{skill_dir.name}: " + "; ".join(violations)
