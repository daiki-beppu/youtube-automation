"""Gemini でコメント返信を動的生成する generator."""

from __future__ import annotations

import logging
import time

from youtube_automation.utils.comments.generator.base import GeneratedReply, ReplyContext
from youtube_automation.utils.exceptions import ValidationError
from youtube_automation.utils.genai_client import create_genai_client
from youtube_automation.utils.image_provider.base import RETRY_BACKOFF, RETRY_MAX

logger = logging.getLogger(__name__)


def _build_prompt(ctx: ReplyContext) -> str:
    prompt_lines = [
        "You are replying to a YouTube comment as the channel host.",
        f"Channel persona: {ctx.channel_persona}",
        f"Video title: {ctx.video_title}",
        f"Comment author: {ctx.comment_author}",
        f"Comment text: {ctx.comment_text}",
        f"Max length: {ctx.max_length} characters",
        "Write 1-3 sentences, warm and sincere, no emoji spam, no pushy CTA.",
    ]
    if ctx.language is not None:
        prompt_lines.append(f"Reply in language: {ctx.language}")
    else:
        prompt_lines.append("Detect the comment language and reply in the same language.")
    return "\n".join(prompt_lines)


def _truncate_reply(text: str, *, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    logger.warning("generated reply exceeded max_length=%d and was truncated", max_length)
    return text[:max_length]


class GeminiGenerator:
    """Vertex AI Gemini backend."""

    def __init__(self, *, model: str, min_interval_sec: float):
        self._client = create_genai_client()
        self._model = model
        self._min_interval_sec = min_interval_sec

    def generate(self, ctx: ReplyContext) -> GeneratedReply:
        if not self._model:
            raise ValidationError("gemini generator requires model")

        prompt = _build_prompt(ctx)
        last_error: Exception | None = None
        for attempt in range(RETRY_MAX):
            try:
                response = self._client.models.generate_content(model=self._model, contents=prompt)
                text = (response.text or "").strip()
                if not text:
                    raise ValidationError("gemini generator returned empty text")
                return GeneratedReply(
                    text=_truncate_reply(text, max_length=ctx.max_length),
                    prompt=prompt,
                )
            except Exception as error:  # noqa: BLE001
                last_error = error
                if attempt == RETRY_MAX - 1:
                    break
                time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])

        assert last_error is not None
        raise last_error
