"""動画生成方式を表す共通契約。

動画タイプと生成エンジンは直交する。たとえば ``loop`` は動画の構成を表し、
Veo はその構成を生成するエンジンの一つにすぎない。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from youtube_automation.infrastructure.errors import ConfigError


class VideoType(str, Enum):
    """サポート済みの動画構成。"""

    LOOP = "loop"
    STATIC = "static"

    @classmethod
    def parse(cls, value: object, *, config_path: str = "video_type") -> "VideoType":
        """設定値を enum に変換し、不正値は設定エラーとして報告する。"""
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            allowed = ", ".join(item.value for item in cls)
            raise ConfigError(f"{config_path} must be one of: {allowed} (got: {value!r})") from exc


@dataclass(frozen=True)
class VideoTypeConfig:
    """skill-config に共通する動画タイプ設定。"""

    video_type: VideoType = VideoType.LOOP

    @classmethod
    def from_mapping(
        cls,
        config: Mapping[str, object] | None,
        *,
        config_path: str = "video_type",
    ) -> "VideoTypeConfig":
        raw_value = (config or {}).get("video_type", VideoType.LOOP.value)
        return cls(video_type=VideoType.parse(raw_value, config_path=config_path))
