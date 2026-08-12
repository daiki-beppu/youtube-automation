"""automation-update skill と CLI help の ownership 境界を検証する。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

SKILL_TEXT = (REPO_ROOT / ".claude/skills/automation-update/SKILL.md").read_text(encoding="utf-8")


def _apply_commands() -> list[str]:
    return re.findall(r"^uv run yt-automation-update apply(?:\s.*)?$", SKILL_TEXT, flags=re.MULTILINE)


def test_skill_keeps_one_representative_apply_command_between_decision_and_smoke_check() -> None:
    commands = _apply_commands()

    assert commands == ["uv run yt-automation-update apply --tag <target_tag>"]
    assert SKILL_TEXT.index("uv run yt-automation-update check") < SKILL_TEXT.index("### Step 2-4.")
    assert SKILL_TEXT.index("### Step 2-4.") < SKILL_TEXT.index(commands[0])
    assert SKILL_TEXT.index(commands[0]) < SKILL_TEXT.index('command = ["uv", "run", "yt-doctor", "--json"]')


def test_skill_keeps_nonintuitive_safety_contracts_owned_by_the_wizard() -> None:
    required_clauses = {
        "--force-sync": ("local fix", "bypass"),
        "--sync-only": ("claude-md", "bypass しない"),
        "--accept-hooks": ("新規 hook", "承認"),
        "--allow-dirty": ("途中失敗", "再実行"),
        "--prune": ("明示同意", "別途実行"),
    }

    for option, clauses in required_clauses.items():
        matching_paragraphs = [paragraph for paragraph in SKILL_TEXT.split("\n\n") if option in paragraph]
        assert any(all(clause in paragraph for clause in clauses) for paragraph in matching_paragraphs), option
