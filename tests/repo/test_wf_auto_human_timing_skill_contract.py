"""`/wf-auto` の同一 run 人間介入 gate timing 契約を検証する。"""

from __future__ import annotations

import re

from tests.helpers.paths import REPO_ROOT

SKILL_MD = REPO_ROOT / ".claude" / "skills" / "wf-auto" / "SKILL.md"


def _section(text: str, heading: str) -> str:
    match = re.search(
        rf"^{re.escape(heading)}\n(?P<body>.*?)(?=^###?\s|\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError(f"`{heading}` セクションが見つかりません")
    return match.group("body")


def test_same_run_human_gate_closes_interval_before_recording_attempt() -> None:
    contract = _section(
        SKILL_MD.read_text(encoding="utf-8"),
        "### 同一 run の人間介入 gate timing 契約",
    )

    gate_start = contract.index("AskUserQuestion または本人操作の依頼を提示する直前")
    gate_end = contract.index("回答または本人操作の完了を受け取った直後")
    record = contract.index("`record` を実行するとき")

    assert gate_start < gate_end < record
    assert contract.count("datetime.now(UTC).isoformat()") == 2
    assert "メインエージェント" in contract
    assert "subagent へ委譲しない" in contract


def test_multiple_human_gates_are_forwarded_in_order_on_the_same_attempt() -> None:
    contract = _section(
        SKILL_MD.read_text(encoding="utf-8"),
        "### 同一 run の人間介入 gate timing 契約",
    )

    assert "<current-attempt-human-intervals>" in contract
    assert "発生順を保ったまま全件" in contract
    assert "同じ attempt" in contract
    command = re.search(r"```bash\n(?P<body>.*?)```", contract, flags=re.DOTALL)
    assert command is not None
    argv = command.group("body")
    assert "--ai-started-at <current-attempt-ai-started-at>" in argv
    first = argv.index("--human-interval <human-start-1> <human-end-1>")
    second = argv.index("--human-interval <human-start-2> <human-end-2>")
    assert first < second


def test_login_and_captcha_remain_limited_to_the_required_human_operation() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    gates = _section(text, "## Hard Gates")
    suno = _section(text, "### `suno-helper` action の自律実行契約")

    assert "login、CAPTCHA" in gates
    assert "自動承認せず `blocked`" in gates
    assert "本人操作が不可欠な場合だけ" in suno
    assert "認証のコマンド実行や CAPTCHA 回避は行わない" in suno
