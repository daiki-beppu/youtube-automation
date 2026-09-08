"""skill-config を画像生成プロバイダーの設定契約へ変換する。"""

from youtube_automation.infrastructure.media.image_provider.config import (
    ImageGenerationConfig,
    parse_image_generation_config,
)


def load_image_generation_config(skill: str = "thumbnail") -> ImageGenerationConfig:
    """指定した skill の既定設定と上書きから画像生成設定を構築する。"""
    from youtube_automation.configuration.skills import load_skill_config

    return parse_image_generation_config(load_skill_config(skill))
