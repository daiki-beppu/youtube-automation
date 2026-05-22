"""コメント返信 generator の共通型."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from youtube_automation.utils.comments.fetcher import FetchedComment


@dataclass(frozen=True)
class ReplyContext:
    """1 件分の返信生成に必要な解決済み入力."""

    video_id: str
    video_title: str
    comment_id: str
    comment_text: str
    comment_author: str
    language: str | None
    channel_persona: str
    max_length: int
    parent_thread: list[FetchedComment] | None
    template_text: str | None = None


@dataclass(frozen=True)
class GeneratedReply:
    """1 件分の返信生成結果."""

    text: str
    prompt: str | None


@runtime_checkable
class ReplyGenerator(Protocol):
    """返信 generator の最小契約."""

    def generate(self, ctx: ReplyContext) -> GeneratedReply: ...
