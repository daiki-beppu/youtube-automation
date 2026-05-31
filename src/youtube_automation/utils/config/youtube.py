"""YouTube API 設定・music_engine・content_model の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class YoutubeApi:
    """`youtube` セクション（API 基本設定）.

    `contains_synthetic_media`: アップロード時に申告する AI 開示フラグ
        (`status.containsSyntheticMedia`)。未設定時は現行の振る舞いに合わせ `True`。
    `self_declared_made_for_kids`: 子供向け申告 (`status.selfDeclaredMadeForKids`)。
        未設定時は現行の振る舞いに合わせ `False`。
    """

    category_id: str
    privacy_status: str
    language: str
    contains_synthetic_media: bool = True
    self_declared_made_for_kids: bool = False


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
