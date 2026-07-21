"""`/live-chat-reply` の運用・routing 契約（#2376）。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_SKILLS = _ROOT / ".claude" / "skills"
_LIVE_CHAT_SKILL = _SKILLS / "live-chat-reply" / "SKILL.md"


def _description(name: str) -> str:
    text = (_SKILLS / name / "SKILL.md").read_text()
    frontmatter = text.split("---", 2)[1]
    return yaml.safe_load(frontmatter)["description"]


def test_sibling_skill_descriptions_are_mutually_exclusive() -> None:
    live_chat = _description("live-chat-reply")
    comments = _description("comments-reply")
    streaming = _description("streaming")

    assert "ライブチャット返信" in live_chat
    assert "/comments-reply" in live_chat
    assert "/streaming" in live_chat
    assert "/live-chat-reply" in comments
    assert "/live-chat-reply" in streaming


def test_skill_puts_hard_gates_and_completion_near_the_top() -> None:
    lines = _LIVE_CHAT_SKILL.read_text().splitlines()
    assert lines.index("## Hard Gates") < 60
    assert lines.index("## 完了条件") < 60
    text = "\n".join(lines)
    assert "config/channel/comments.json" in text
    assert "terraform version" in text
    assert "auth/token.json" in text
    assert "${CODEX_HOME:-$HOME/.codex}/auth.json" in text


def test_skill_keeps_authentication_human_and_commands_ai_owned() -> None:
    text = _LIVE_CHAT_SKILL.read_text()
    assert "AI が `uv run yt-oauth`" in text
    assert "AI が `codex login`" in text
    assert "AI が `op signin`" in text
    assert "人間はブラウザ上のログイン・アカウント選択・同意だけ" in text
    assert "write_op_secret" in text
    assert "JSON template を stdin" in text


def test_skill_has_irreversible_apply_gate_and_end_to_end_verification() -> None:
    text = _LIVE_CHAT_SKILL.read_text()
    assert "配備する」「キャンセル" in text
    assert "投稿は取り消せない" in text
    assert "--auto-approve" in text
    assert "deploy_live_chat.sh" in text
    assert "systemctl is-active youtube-stream live-chat-reply" in text
    assert "stat -c" in text
    assert "journalctl -u live-chat-reply" in text


def test_example_exposes_every_documented_live_chat_setting() -> None:
    config = json.loads((_ROOT / "examples/channel_config.example/comments.json").read_text())
    live_chat = config["comments"]["live_chat"]
    expected = {
        "enabled",
        "language",
        "ng_words",
        "max_length",
        "max_replies_per_hour",
        "max_consecutive_per_user",
        "daily_quota_budget",
        "reply_quota_cost",
        "no_broadcast_retry_sec",
        "history_file",
        "channel_persona",
        "model",
        "codex_timeout_sec",
        "process_initial_messages",
    }
    assert set(live_chat) == expected
    assert live_chat["enabled"] is False
    assert live_chat["process_initial_messages"] is False
