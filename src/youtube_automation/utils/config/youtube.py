"""YouTube API 設定・music_engine・content_model の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class YoutubeApi:
    """`youtube` セクション（API 基本設定）."""

    category_id: str
    privacy_status: str
    language: str


@dataclass(frozen=True)
class ContentModel:
    """`content_model` セクション（optional）.

    `type`: `"release"` / `"collection"` など。
    `languages`: 配信対象言語。未指定時は loader が `[api.language]` を注入する。
    """

    type: str = "release"
    languages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class YoutubeSection:
    """YouTube 責務の合成."""

    api: YoutubeApi
    music_engine: str
    content_model: ContentModel
