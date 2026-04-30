"""image_provider のファクトリ関数 `get_provider()` の単体テスト。

`ImageGenerationConfig.provider` の値に応じて
`GeminiImageProvider` / `OpenAIImageProvider` の正しい実装が返されることを検証する。
"""

from __future__ import annotations

import pytest
from youtube_automation.utils.image_provider import get_provider
from youtube_automation.utils.image_provider.config import (
    GeminiConfig,
    ImageGenerationConfig,
    OpenAIConfig,
)
from youtube_automation.utils.image_provider.gemini import GeminiImageProvider
from youtube_automation.utils.image_provider.openai import OpenAIImageProvider

from youtube_automation.utils.exceptions import ConfigError


def _gemini_config() -> ImageGenerationConfig:
    return ImageGenerationConfig(
        provider="gemini",
        gemini=GeminiConfig(model="gemini-3.1-flash-image-preview", image_size="2K"),
        openai=None,
    )


def _openai_config() -> ImageGenerationConfig:
    return ImageGenerationConfig(
        provider="openai",
        gemini=None,
        openai=OpenAIConfig(
            model="gpt-image-2",
            quality="high",
            aspect_ratio="16:9",
            thinking="medium",
            batch=1,
        ),
    )


class TestGetProvider:
    def test_returns_gemini_provider_when_provider_is_gemini(self):
        # Given
        cfg = _gemini_config()

        # When
        provider = get_provider(cfg)

        # Then
        assert isinstance(provider, GeminiImageProvider)
        assert provider.name == "gemini"

    def test_returns_openai_provider_when_provider_is_openai(self):
        # Given
        cfg = _openai_config()

        # When
        provider = get_provider(cfg)

        # Then
        assert isinstance(provider, OpenAIImageProvider)
        assert provider.name == "openai"

    def test_unknown_provider_raises_config_error(self):
        # Given: 強制的に provider 名を破壊（ImageGenerationConfig は frozen でも
        # __setattr__ をバイパスして実装側のガードを試す）
        cfg = _gemini_config()
        object.__setattr__(cfg, "provider", "midjourney")

        # When / Then
        with pytest.raises(ConfigError, match="midjourney"):
            get_provider(cfg)

    def test_gemini_provider_exposes_pricing_model_id(self):
        # Given
        cfg = _gemini_config()

        # When
        provider = get_provider(cfg)

        # Then: cost_tracker.PRICING のキーと一致する
        from youtube_automation.utils import cost_tracker

        assert provider.pricing_model_id in cost_tracker.PRICING
        assert provider.pricing_model_id == "gemini-3.1-flash-image-preview"

    def test_openai_provider_exposes_pricing_model_id(self):
        # Given
        cfg = _openai_config()

        # When
        provider = get_provider(cfg)

        # Then
        from youtube_automation.utils import cost_tracker

        assert provider.pricing_model_id in cost_tracker.PRICING
        assert provider.pricing_model_id == "gpt-image-2"


class TestSupportedAspectRatios:
    def test_openai_supports_only_16_9_and_9_16(self):
        # Given
        provider = get_provider(_openai_config())

        # When / Then: OpenAI は 16:9 / 9:16 のみサポート
        assert set(provider.supported_aspect_ratios) == {"16:9", "9:16"}

    def test_gemini_does_not_restrict_aspect_ratios(self):
        # Given
        provider = get_provider(_gemini_config())

        # When / Then: Gemini は branding/icon.png 用途で 1:1 等を受け付ける
        # supported_aspect_ratios は空タプル or 全許可マーカーで表現
        assert len(provider.supported_aspect_ratios) == 0 or "16:9" in provider.supported_aspect_ratios
