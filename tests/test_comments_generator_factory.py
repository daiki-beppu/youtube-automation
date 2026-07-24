"""comments reply generator factory の単体テスト."""

from __future__ import annotations

import pytest

from youtube_automation.configuration.comments import GeneratorConfig
from youtube_automation.infrastructure.errors import ConfigError
from youtube_automation.utils import comments as comments_api
from youtube_automation.utils.comments.generator import GeminiGenerator
from youtube_automation.utils.comments.generator_factory import create_reply_generator


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
    generator = create_reply_generator(_config("gemini", model="gemini-3.5-flash"), sleep_fn=lambda _: None)

    assert isinstance(generator, GeminiGenerator)


def test_create_codex_generator_rejects_direct_generation():
    with pytest.raises(ConfigError, match="監査済みフロー"):
        create_reply_generator(_config("codex"), sleep_fn=lambda _: None)


def test_comments_package_facade_exports_only_public_reply_api():
    assert comments_api.__all__ == ["CommentReplier", "ReplyPlan"]
    assert not hasattr(comments_api, "CodexGenerator")
    assert not hasattr(comments_api, "GeminiGenerator")
    assert not hasattr(comments_api, "ReplyHistory")
    assert not hasattr(comments_api, "fetch_comments")


def test_unknown_provider_raises_config_error():
    cfg = object.__new__(GeneratorConfig)
    object.__setattr__(cfg, "provider", "openai")
    object.__setattr__(cfg, "model", None)
    object.__setattr__(cfg, "max_length", 280)
    object.__setattr__(cfg, "requests_per_minute", 30)

    with pytest.raises(ConfigError, match="provider"):
        create_reply_generator(cfg, sleep_fn=lambda _: None)
