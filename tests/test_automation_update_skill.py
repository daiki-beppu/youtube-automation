from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SKILL_MD = _REPO_ROOT / ".claude" / "skills" / "automation-update" / "SKILL.md"


def test_automation_update_guides_user_when_outside_channel_repo() -> None:
    text = _SKILL_MD.read_text(encoding="utf-8")

    assert "対象外フォルダで起動された場合" in text
    assert "現在地が不適切な理由" in text
    assert "移動先候補のチャンネルフォルダ" in text
    assert "print_channel_repo_guidance" in text
    assert "現在地: $(pwd)" in text
    assert "youtube-channels-automation を依存として参照するチャンネルリポジトリではありません" in text
    assert "cd $repo_dir" in text
    assert "xargs grep -l 'youtube-channels-automation'" in text
    assert "チャンネルリポジトリ側へ cd してから /automation-update を再実行してください" in text
