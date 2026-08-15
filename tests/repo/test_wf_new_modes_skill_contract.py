"""`/wf-new` の排他 mode と統合契約を検証する。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

SKILL_DIR = REPO_ROOT / ".claude" / "skills" / "wf-new"
SKILL_MD = SKILL_DIR / "SKILL.md"
AUTO_MD = SKILL_DIR / "references" / "auto.md"


def _section(text: str, heading: str) -> str:
    match = re.search(
        rf"^{re.escape(heading)}\n(?P<body>.*?)(?=^##\s|\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError(f"`{heading}` セクションが見つかりません")
    return match.group("body")


def test_mode_dispatch_is_exclusive_before_any_mutation() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    mode = _section(skill, "## モード判定")

    assert skill.index("## モード判定") < skill.index("## 前提")
    assert "$ARGUMENTS" in mode
    assert "2 個以上" in mode
    assert "state・lease・成果物は一切変更しない" in mode
    assert "1 個なら" in mode
    assert "0 個なら従来の通常入口" in mode
    assert "| `--auto` | `references/auto.md` |" in mode
    assert "| `--batch` | `references/batch.md` |" in mode
    assert "| `--schedule` | `references/schedule.md` |" in mode
    assert "完全一致" in mode
    assert "`--batch-id`" in mode


def test_schedule_mode_preserves_status_disable_and_safety_contracts() -> None:
    schedule = (SKILL_DIR / "references" / "schedule.md").read_text(encoding="utf-8")

    assert "## Task: setup / update" in schedule
    assert "## status" in schedule
    assert "## disable" in schedule
    assert "allow_external_publish: true" in schedule
    assert "dry-run" in schedule
    assert "--confirm-os-fallback" in schedule
    assert not (SKILL_DIR.parent / "automation-schedule").exists()


def test_batch_modifiers_are_not_modes() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")
    modifiers = _section(skill, "## 修飾フラグ")

    assert "| `--count <N>` | `--batch` |" in modifiers
    assert "| `--resume <batch-id>` | `--batch` |" in modifiers


def test_auto_mode_reuses_the_normal_entry_for_wf_new_action() -> None:
    auto = AUTO_MD.read_text(encoding="utf-8")

    assert "resolver が `action: wf-new`" in auto
    assert "同一 SKILL.md の通常入口" in auto
    for gate in ("企画選択", "thumbnail 承認", "preselected manifest", "channel constraint verification"):
        assert gate in auto
