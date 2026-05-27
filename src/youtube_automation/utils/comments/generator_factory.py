"""コメント返信 generator の provider factory."""

from __future__ import annotations

import time
from collections.abc import Callable

from youtube_automation.utils.comments.codex_generator import CodexGenerator
from youtube_automation.utils.comments.generator import GeminiGenerator, ReplyGenerator
from youtube_automation.utils.config.comments import PROVIDER_CODEX, PROVIDER_GEMINI, GeneratorConfig
from youtube_automation.utils.exceptions import ConfigError


def create_reply_generator(
    config: GeneratorConfig,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> ReplyGenerator:
    if config.provider == PROVIDER_GEMINI:
        if config.model is None:
            raise ConfigError("comments.generator.provider='gemini' の場合 model は必須です")
        return GeminiGenerator(
            model=config.model,
            max_length=config.max_length,
            requests_per_minute=config.requests_per_minute,
            sleep_fn=sleep_fn,
        )
    if config.provider == PROVIDER_CODEX:
        return CodexGenerator(
            model=config.model,
            max_length=config.max_length,
            requests_per_minute=config.requests_per_minute,
            sleep_fn=sleep_fn,
        )
    raise ConfigError(f"comments.generator.provider 未対応: {config.provider!r}")
