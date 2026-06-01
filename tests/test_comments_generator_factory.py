"""comments reply generator factory の単体テスト."""

from __future__ import annotations

import pytest

from youtube_automation.utils.comments.codex_generator import CodexGenerator
from youtube_automation.utils.comments.generator import GeminiGenerator
from youtube_automation.utils.comments.generator_factory import create_reply_generator
from youtube_automation.utils.config.comments import GeneratorConfig
from youtube_automation.utils.exceptions import ConfigError


def _config(provider: str, *, model: str | None = None) -> GeneratorConfig:
    return GeneratorConfig(
        provider=provider,
        model=model,
        channel_persona="persona",
        max_length=280,
        fallback_on_error="skip",
        requests_per_minute=30,
    )


def test_create_gemini_generator():
    generator = create_reply_generator(_config("gemini", model="gemini-2.5-pro"), sleep_fn=lambda _: None)

    assert isinstance(generator, GeminiGenerator)


def test_create_codex_generator():
    generator = create_reply_generator(_config("codex"), sleep_fn=lambda _: None)

    assert isinstance(generator, CodexGenerator)


def test_unknown_provider_raises_config_error():
    cfg = object.__new__(GeneratorConfig)
    object.__setattr__(cfg, "provider", "openai")
    object.__setattr__(cfg, "model", None)
    object.__setattr__(cfg, "max_length", 280)
    object.__setattr__(cfg, "requests_per_minute", 30)

    with pytest.raises(ConfigError, match="provider"):
        create_reply_generator(cfg, sleep_fn=lambda _: None)
