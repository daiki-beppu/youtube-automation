"""Prompt safety helpers for comment-reply generators."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from youtube_automation.utils.comments.generator import ReplyContext


def viewer_payload_json(ctx: "ReplyContext") -> str:
    """Encode untrusted viewer fields as JSON safe for XML-like prompt tags."""
    payload = json.dumps(
        {"commenter": ctx.comment_author, "comment": ctx.comment_text},
        ensure_ascii=False,
    )
    return payload.replace("</", "<\\/")
