"""`.claude/skills/masterup/SKILL.md` の現行 timestamp 契約を検証する。"""

from __future__ import annotations

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_MASTERUP_SKILL_MD = _REPO_ROOT / ".claude" / "skills" / "masterup" / "SKILL.md"


def _read_masterup_skill() -> str:
    return _MASTERUP_SKILL_MD.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^##+\s*{re.escape(heading)}\b.*?(?=^##+\s|\Z)", text, flags=re.MULTILINE | re.DOTALL)
    if match is None:
        raise AssertionError(f"masterup/SKILL.md に {heading!r} セクションが見つかりません")
    return match.group(0)


def test_quick_reference_does_not_advertise_legacy_fix_timestamps() -> None:
    quick_reference = _section(_read_masterup_skill(), "Quick Reference")

    assert "yt-fix-timestamps" not in quick_reference


def test_step_5_7_documents_metadata_generator_as_current_timestamp_path() -> None:
    step_5_7 = _section(_read_masterup_skill(), "Step 5.7: タイムスタンプ整合性")

    assert "metadata_generator.generate_timestamps()" in step_5_7
    assert "format_timestamps_text()" in step_5_7
    assert "通常フローでは実行しない" in step_5_7
    assert "自動実行する" not in step_5_7
