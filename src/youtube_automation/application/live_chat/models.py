"""ライブチャットのドメインモデル."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiveChatMessage:
    message_id: str
    author_channel_id: str
    author_name: str
    text: str
    published_at: str


@dataclass(frozen=True)
class ReplyDecision:
    should_reply: bool
    reply_text: str
    reason: str
