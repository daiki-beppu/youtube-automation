"""`/wf-next` 直接実行の canonical timing 契約を検証する。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

WF_NEXT_SKILL = REPO_ROOT / ".claude" / "skills" / "wf-next" / "SKILL.md"
WF_AUTO_SKILL = REPO_ROOT / ".claude" / "skills" / "wf-new" / "references" / "auto.md"


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


def test_direct_entry_plans_the_fixed_collection_before_starting_work() -> None:
    direct = _section(WF_NEXT_SKILL.read_text(encoding="utf-8"), "### 直接実行の canonical timing 契約")
    canonical = WF_AUTO_SKILL.read_text(encoding="utf-8")

    assert _state_script_assignment(direct) == _state_script_assignment(canonical)
    commands = [
        "acquire --channel-dir .",
        "plan --channel-dir . --collection <fixed-name>",
        "heartbeat --channel-dir . --token <token>",
        "datetime.now(UTC).isoformat()",
    ]
    positions = [direct.index(command) for command in commands]
    assert positions == sorted(positions)
    assert "`status: refreshed`" in direct
    assert "`status: not-owner`" in direct
    assert "exit 0 だけでは owner と判定しない" in direct
    for action in (
        "wf-new",
        "lyria",
        "minimax",
        "suno-helper",
        "masterup",
        "wf-next-local",
        "wf-next",
        "publish",
        "blocked",
        "complete",
    ):
        assert f"`{action}`" in direct
    assert "resolver が返した固定 collection" in direct


def test_direct_entry_records_every_status_with_the_resolver_decision() -> None:
    direct = _section(WF_NEXT_SKILL.read_text(encoding="utf-8"), "### 直接実行の canonical timing 契約")

    record = next(line for line in direct.splitlines() if "record --channel-dir" in line)
    assert "--collection <fixed-name>" in record
    assert "--action <resolver-action>" in record
    assert "--status success|blocked|failed" in record
    assert "--ai-started-at <current-attempt-ai-started-at>" in record
    assert "同じ attempt" in direct
    assert "成果物と state を検証" in direct
    assert "plan --channel-dir . --collection <fixed-name>" in direct


def test_action_selection_and_existing_gates_keep_their_canonical_owners() -> None:
    text = WF_NEXT_SKILL.read_text(encoding="utf-8")
    direct = _section(text, "### 直接実行の canonical timing 契約")

    assert "公開許可や実成果物から action を独自再判定せず" in direct
    assert "既存の成果物検証、承認 gate、state 更新責務" in direct
    assert "## Hard Gates: subagent 委譲境界" in text
    assert "## 承認ゲート（config 駆動）" in text


def test_prepared_phase_actions_keep_their_existing_direct_handlers() -> None:
    text = WF_NEXT_SKILL.read_text(encoding="utf-8")
    direct = _section(text, "### 直接実行の canonical timing 契約")

    for action in ("lyria", "minimax", "suno-helper", "masterup", "wf-next-local", "wf-next"):
        assert f"`{action}`" in direct
    assert "prepared" in direct
    assert "既存のフェーズ別処理" in direct
    assert "別 action へ読み替えない" in direct
    assert "#### `prepared` → 段階的サポート" in text


def test_delegation_reuses_one_lease_attempt_and_history_record() -> None:
    direct = _section(WF_NEXT_SKILL.read_text(encoding="utf-8"), "### 直接実行の canonical timing 契約")

    assert "実行文脈を再利用" in direct
    assert "nested `acquire`" in direct
    assert "canonical history の記録と lease 解放は `/wf-new --auto` に一度だけ" in direct
    assert "release --channel-dir . --token <token>" in direct
    assert "他 token" in direct


def test_upload_plan_propagates_the_canonical_duration_approval() -> None:
    text = WF_NEXT_SKILL.read_text(encoding="utf-8")
    publishing = _section(text, "#### `mastered` → 公開フロー（アップロード承認ゲートあり）")
    approval_gate = publishing[publishing.index("3. **アップロード承認ゲート") :]

    plan_command = "uv run yt-upload-collection --plan [-c <collection-name>] [--allow-duration-outside-target]"
    assert plan_command in approval_gate
    assert "resolver の `allow_duration_outside_target` が true の場合" in approval_gate
    assert "アップロード承認ゲートの plan に `--allow-duration-outside-target`" in approval_gate
