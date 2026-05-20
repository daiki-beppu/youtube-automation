"""image_provider のファクトリ関数 `get_provider()` の単体テスト。

`ImageGenerationConfig.provider` の値に応じて
`GeminiImageProvider` / `OpenAIImageProvider` / `CodexImageProvider` の
正しい実装が返されることを検証する。
"""

from __future__ import annotations

import subprocess

import pytest

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider import get_provider
from youtube_automation.utils.image_provider.config import (
    CodexConfig,
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
        codex=None,
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
        codex=None,
    )


def _codex_config() -> ImageGenerationConfig:
    return ImageGenerationConfig(
        provider="codex",
        gemini=None,
        openai=None,
        codex=CodexConfig(
            model="gpt-image-1",
            image_size="1024x1024",
            aspect_ratio="16:9",
            timeout_seconds=300,
        ),
    )


@pytest.fixture
def stub_codex_login(monkeypatch):
    """`CodexImageProvider` のコンストラクタが走らせる `codex login status` を mock する。"""
    import youtube_automation.utils.image_provider.codex as codex_mod

    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="Logged in using ChatGPT",
            stderr="",
        )

    monkeypatch.setattr(codex_mod.subprocess, "run", _fake_run)
    monkeypatch.setattr(codex_mod.shutil, "which", lambda _: "/fake/codex")


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

    def test_returns_codex_provider_when_provider_is_codex(self, stub_codex_login):
        # Given: codex CLI が "Logged in" を返す状態（fixture で mock 済み）
        from youtube_automation.utils.image_provider.codex import CodexImageProvider

        cfg = _codex_config()

        # When
        provider = get_provider(cfg)

        # Then
        assert isinstance(provider, CodexImageProvider)
        assert provider.name == "codex"

    def test_get_provider_raises_when_codex_config_missing(self):
        # Given: provider=codex なのに codex sub-config が None
        cfg = ImageGenerationConfig(provider="codex", gemini=None, openai=None, codex=None)

        # When / Then
        with pytest.raises(ConfigError, match="provider=codex"):
            get_provider(cfg)

    def test_unknown_provider_raises_config_error(self):
        # Given: 強制的に provider 名を破壊（ImageGenerationConfig は frozen でも
        # __setattr__ をバイパスして実装側のガードを試す）
        cfg = _gemini_config()
        object.__setattr__(cfg, "provider", "midjourney")

        # When / Then
        with pytest.raises(ConfigError, match="midjourney"):
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

    def test_codex_supports_16_9_9_16_and_1_1(self, stub_codex_login):
        # Given / When
        provider = get_provider(_codex_config())

        # Then: imagegen ツール出力の安定性確保のため 3 比率に制限
        assert set(provider.supported_aspect_ratios) == {"16:9", "9:16", "1:1"}
