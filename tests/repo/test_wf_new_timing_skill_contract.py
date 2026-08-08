"""`/wf-new` 直接実行の canonical timing 契約を検証する。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

WF_NEW_SKILL = REPO_ROOT / ".claude" / "skills" / "wf-new" / "SKILL.md"
WF_AUTO_SKILL = REPO_ROOT / ".claude" / "skills" / "wf-auto" / "SKILL.md"


def _section(text: str, heading: str) -> str:
    match = re.search(
        rf"^{re.escape(heading)}\n(?P<body>.*?)(?=^##+\s|\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError(f"`{heading}` セクションが見つかりません")
    return match.group("body")


def _state_script_assignment(text: str) -> str:
    match = re.search(r"^STATE_SCRIPT=(?P<path>\S+)$", text, flags=re.MULTILINE)
    if not match:
        raise AssertionError("STATE_SCRIPT assignment が見つかりません")
    return match.group("path")


def test_direct_entry_uses_the_canonical_resolver_before_starting_work() -> None:
    direct = _section(WF_NEW_SKILL.read_text(encoding="utf-8"), "### 直接実行の canonical timing 契約")
    canonical = WF_AUTO_SKILL.read_text(encoding="utf-8")

    assert _state_script_assignment(direct) == _state_script_assignment(canonical)
    commands = [
        "acquire --channel-dir .",
        "plan --channel-dir .",
        "heartbeat --channel-dir . --token <token>",
        "datetime.now(UTC).isoformat()",
    ]
    positions = [direct.index(command) for command in commands]
    assert positions == sorted(positions)
    assert "`status: refreshed`" in direct
    assert "`status: not-owner`" in direct
    assert "exit 0 だけでは owner と判定しない" in direct
    assert "resolver が返した `action: wf-new`" in direct
    assert "resolver が返した collection" in direct


def test_direct_entry_closes_bootstrap_and_fixed_collection_attempts() -> None:
    direct = _section(WF_NEW_SKILL.read_text(encoding="utf-8"), "### 直接実行の canonical timing 契約")

    bootstrap = next(line for line in direct.splitlines() if "record-bootstrap" in line)
    assert "--status blocked|failed" in bootstrap
    assert "--ai-started-at <current-attempt-ai-started-at>" in bootstrap
    assert "--human-interval <human-start> <human-end>" in bootstrap
    assert "発生順" in direct

    record = next(line for line in direct.splitlines() if "record --channel-dir" in line)
    assert "--collection <fixed-name>" in record
    assert "--action wf-new" in record
    assert "--status success|blocked|failed" in record
    assert "--ai-started-at <current-attempt-ai-started-at>" in record
    assert "出力 path" in direct
    assert "workflow-state.json" in direct
    assert "同じ fixed collection" in direct
    assert "同じ attempt" in direct


def test_direct_entry_releases_only_its_own_lease_on_every_exit() -> None:
    direct = _section(WF_NEW_SKILL.read_text(encoding="utf-8"), "### 直接実行の canonical timing 契約")

    assert "`finally` 相当" in direct
    assert "release --channel-dir . --token <token>" in direct
    assert "他 token" in direct


def test_wf_auto_delegation_reuses_one_lease_and_attempt() -> None:
    direct = _section(WF_NEW_SKILL.read_text(encoding="utf-8"), "### 直接実行の canonical timing 契約")

    assert "実行文脈を再利用" in direct
    assert "nested `acquire`" in direct
    assert "canonical history の記録と lease 解放は `/wf-auto` に一度だけ" in direct
