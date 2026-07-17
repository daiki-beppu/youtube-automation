"""SKILL.md frontmatter が strict YAML (PyYAML safe_load) で安全に読めることを検証する (Issue #652)。

description 値内の `: ` (コロン+スペース) は strict YAML ではマッピング区切りと
誤解釈されパースが破綻する。全 skill の frontmatter を double-quoted string に統一し、
将来 strict YAML パーサで読む経路が追加されても壊れないことを保証する。

検証ロジックの単一ソースは `yt-skills lint` 側
(youtube_automation.cli.skills_sync._lint) にあり、本テストはそれを全 skill に
適用する回帰テスト (Issue #2096)。判定基準を変える場合は _lint 側を修正すること。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.cli.skills_sync._lint import lint_skill

# リポジトリルート (tests/ の親)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"

_SKILL_DIRS = sorted(p.parent for p in _SKILLS_DIR.glob("*/SKILL.md"))


def test_skill_files_discovered() -> None:
    # Given: .claude/skills 配下の SKILL.md
    # Then: 1 件以上見つかる (glob が空でないことを保証)
    assert _SKILL_DIRS, f"SKILL.md が見つかりません: {_SKILLS_DIR}"


@pytest.mark.parametrize("skill_dir", _SKILL_DIRS, ids=lambda p: p.name)
def test_frontmatter_passes_lint(skill_dir: Path) -> None:
    # Given: skill ディレクトリ
    # When: yt-skills lint と同一の検証ロジックを適用する
    violations = lint_skill(skill_dir)

    # Then: 違反ゼロ (strict YAML パース / name・description 非空 / double-quote)
    assert not violations, f"{skill_dir.name}: " + "; ".join(violations)
