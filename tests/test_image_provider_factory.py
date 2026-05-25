"""image_provider のファクトリ関数 `get_provider()` の単体テスト。

`ImageGenerationConfig.provider` の値に応じて
`GeminiImageProvider` / `OpenAIImageProvider` の正しい実装が返されることを検証する。
"""

from __future__ import annotations

import pytest

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider import get_provider
from youtube_automation.utils.image_provider.config import (
    GeminiConfig,
    ImageGenerationConfig,
    OpenAIConfig,
)
from youtube_automation.utils.image_provider.gemini import GeminiImageProvider
from youtube_automation.utils.image_provider.openai import OpenAIImageProvider


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


def _codex_config() -> ImageGenerationConfig:
    return ImageGenerationConfig(provider="codex", gemini=None, openai=None)


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

    def test_codex_provider_is_rejected_from_api_factory_with_route_guidance(self):
        """Given provider=codex の ImageGenerationConfig
        When API provider factory を呼ぶ
        Then ImageProvider 実装は返さず codex-image.sh 経路へ誘導する。
        """
        # Given
        cfg = _codex_config()

        # When / Then
        with pytest.raises(ConfigError, match="codex-image\\.sh"):
            get_provider(cfg)

    def test_gemini_provider_does_not_expose_pricing_model_id(self):
        """Issue #132: PRICING 撤廃に伴い `pricing_model_id` 属性も削除する。

        Given Gemini provider インスタンス
        When `pricing_model_id` 属性を引く
        Then 属性が存在しない (PRICING キー紐付けの責務自体が消えるため)。
        """
        # Given
        cfg = _gemini_config()

        # When
        provider = get_provider(cfg)

        # Then
        assert not hasattr(provider, "pricing_model_id"), "pricing_model_id がまだ残っている (PRICING 撤廃と整合しない)"

    def test_openai_provider_does_not_expose_pricing_model_id(self):
        """Issue #132: PRICING 撤廃に伴い `pricing_model_id` 属性も削除する。

        Given OpenAI provider インスタンス
        When `pricing_model_id` 属性を引く
        Then 属性が存在しない。
        """
        # Given
        cfg = _openai_config()

        # When
        provider = get_provider(cfg)

        # Then
        assert not hasattr(provider, "pricing_model_id"), "pricing_model_id がまだ残っている (PRICING 撤廃と整合しない)"


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
