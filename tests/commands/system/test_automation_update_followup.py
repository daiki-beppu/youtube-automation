from __future__ import annotations

import subprocess
from pathlib import Path

from youtube_automation.commands.system.automation_update_followup import (
    CommandRunner,
    migrate_action,
    render_action,
)

_CHANNEL = Path("/channel")


def _runner(stdout: str, returncode: int) -> CommandRunner:
    def run(command: list[str], path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, returncode, stdout, "")

    return run


def _unstartable(command: list[str], path: Path) -> subprocess.CompletedProcess[str]:
    raise OSError("uv を起動できません")


def test_migrate_action_detects_pending_migration() -> None:
    assert migrate_action(_CHANNEL, _runner("dry-run 完了: 1 ファイル（変更なし）", 0)) == "要 migrate"
    assert migrate_action(_CHANNEL, _runner("移行対象はありません", 0)) is None


def test_render_action_detects_stale_document_pairs() -> None:
    assert render_action(_CHANNEL, _runner("stale 1 document pair(s)", 1)) == "要 render"
    assert render_action(_CHANNEL, _runner("", 0)) is None


def test_unstartable_command_degrades_to_a_check_failure() -> None:
    """例外を呼び出し側へ漏らすと、追従済みの通知ごと握り潰されてしまう。"""
    assert migrate_action(_CHANNEL, _unstartable) == "migrate 検査に失敗"
    assert render_action(_CHANNEL, _unstartable) == "render 検査に失敗"
