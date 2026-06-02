"""SKILL.md frontmatter が strict YAML (PyYAML safe_load) で安全に読めることを検証する (Issue #652)。

description 値内の `: ` (コロン+スペース) は strict YAML ではマッピング区切りと
誤解釈されパースが破綻する。全 skill の frontmatter を double-quoted string に統一し、
将来 strict YAML パーサで読む経路が追加されても壊れないことを保証する。

非実行資産 (説明本文) の文言は固定しない。機械処理される契約 — frontmatter が
safe_load で name/description を持つ dict として解釈できること — のみを検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# リポジトリルート (tests/ の親)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"

_FRONTMATTER_DELIMITER = "---"

_SKILL_FILES = sorted(_SKILLS_DIR.glob("*/SKILL.md"))


def _extract_frontmatter(text: str) -> str:
    """先頭の `---` から次の `---` までの frontmatter ブロックを返す。"""
    lines = text.split("\n")
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        raise AssertionError("SKILL.md が frontmatter デリミタ '---' で始まっていません")
    for i in range(1, len(lines)):
        if lines[i].strip() == _FRONTMATTER_DELIMITER:
            return "\n".join(lines[1:i])
    raise AssertionError("frontmatter の閉じデリミタ '---' が見つかりません")


def test_skill_files_discovered() -> None:
    # Given: .claude/skills 配下の SKILL.md
    # Then: 1 件以上見つかる (glob が空でないことを保証)
    assert _SKILL_FILES, f"SKILL.md が見つかりません: {_SKILLS_DIR}"


@pytest.mark.parametrize("skill_md", _SKILL_FILES, ids=lambda p: p.parent.name)
def test_frontmatter_parses_with_strict_yaml(skill_md: Path) -> None:
    # Given: SKILL.md の frontmatter
    frontmatter = _extract_frontmatter(skill_md.read_text(encoding="utf-8"))

    # When: strict YAML (safe_load) で解釈する
    parsed = yaml.safe_load(frontmatter)

    # Then: name / description を持つ dict として解釈でき、いずれも非空文字列
    assert isinstance(parsed, dict), "frontmatter が dict として解釈できません"
    for key in ("name", "description"):
        assert key in parsed, f"frontmatter に '{key}' がありません"
        assert isinstance(parsed[key], str), f"'{key}' が文字列ではありません"
        assert parsed[key].strip(), f"'{key}' が空です"
