"""Prompt safety helpers for comment-reply generators."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from youtube_automation.utils.comments.generator import ReplyContext


def untrusted_payload_json(payload: dict[str, str]) -> str:
    """Encode untrusted viewer-controlled fields for an XML-like prompt boundary."""
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def viewer_payload_json(ctx: "ReplyContext") -> str:
    """Encode untrusted viewer fields as JSON safe for XML-like prompt tags."""
    return untrusted_payload_json(
        {"commenter": ctx.comment_author, "comment": ctx.comment_text},
    )
