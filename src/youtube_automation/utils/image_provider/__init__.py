"""画像生成プロバイダー抽象化レイヤ。

公開 API:
- ``get_provider(cfg)``: ``ImageGenerationConfig`` から ``ImageProvider`` 実装にディスパッチ
- ``load_image_generation_config()``: thumbnail skill-config から `ImageGenerationConfig` を構築
- ``ImageGenerationRequest`` / ``ImageGenerationResult`` / ``ImageProvider``
- ``RETRY_MAX`` / ``RETRY_BACKOFF``: 共通リトライ定数
"""

from __future__ import annotations

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.image_provider.base import (
    RETRY_BACKOFF,
    RETRY_MAX,
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageProvider,
)
from youtube_automation.utils.image_provider.config import (
    ImageGenerationConfig,
    parse_image_generation_config,
)

__all__ = [
    "ImageGenerationConfig",
    "ImageGenerationRequest",
    "ImageGenerationResult",
    "ImageProvider",
    "RETRY_BACKOFF",
    "RETRY_MAX",
    "get_provider",
    "load_image_generation_config",
    "parse_image_generation_config",
]


def get_provider(cfg: ImageGenerationConfig) -> ImageProvider:
    """``ImageGenerationConfig`` から対応する provider 実装を返す。

    未知の provider 名は ``ConfigError``。
    """
    if cfg.provider == "gemini":
        from youtube_automation.utils.image_provider.gemini import GeminiImageProvider

        if cfg.gemini is None:
            raise ConfigError("provider=gemini だが gemini 設定が見つかりません")
        return GeminiImageProvider(cfg.gemini)

    if cfg.provider == "openai":
        from youtube_automation.utils.image_provider.openai import OpenAIImageProvider

        if cfg.openai is None:
            raise ConfigError("provider=openai だが openai 設定が見つかりません")
        return OpenAIImageProvider(cfg.openai)

    if cfg.provider == "codex":
        from youtube_automation.utils.image_provider.codex import CodexImageProvider

        if cfg.codex is None:
            raise ConfigError("provider=codex だが codex 設定が見つかりません")
        return CodexImageProvider(cfg.codex)

    raise ConfigError(f"未対応の provider={cfg.provider!r}")


def load_image_generation_config(skill: str = "thumbnail") -> ImageGenerationConfig:
    """skill-config をロードして ``ImageGenerationConfig`` を返す薄いラッパ。

    後方互換: ユーザー override が `gemini_image:` のみで `image_generation:` を
    持たない場合は legacy パスに分岐する。default.yaml が `image_generation:` を
    宣言しているため通常マージでは default 値で上書きされ、ユーザーの旧 namespace
    上書きが silently 破棄されてしまう問題への対策。
    """
    from youtube_automation.utils.skill_config import load_channel_override, load_skill_config

    override = load_channel_override(skill)
    user_set_legacy = isinstance(override.get("gemini_image"), dict)
    user_set_new = isinstance(override.get("image_generation"), dict)

    if user_set_legacy and not user_set_new:
        return parse_image_generation_config({"gemini_image": override["gemini_image"]})

    return parse_image_generation_config(load_skill_config(skill))
