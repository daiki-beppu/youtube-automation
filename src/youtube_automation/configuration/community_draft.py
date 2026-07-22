"""コミュニティ投稿バッチ設定の責務別 dataclass（optional）."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from youtube_automation.utils.exceptions import ConfigError

_SCHEDULE_TIME_PATTERN = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


@dataclass(frozen=True)
class CommunityDraftPost:
    """`community_draft.posts[]` の投稿テンプレート."""

    label: str
    template: str
    schedule_offset_days: int
    schedule_time: str
    image: str

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ConfigError("community_draft.posts[].label は空文字にできません")
        if not self.template.strip():
            raise ConfigError("community_draft.posts[].template は空文字にできません")
        if isinstance(self.schedule_offset_days, bool) or not isinstance(self.schedule_offset_days, int):
            raise ConfigError("community_draft.posts[].schedule_offset_days は整数でなければなりません")
        if _SCHEDULE_TIME_PATTERN.fullmatch(self.schedule_time) is None:
            raise ConfigError("community_draft.posts[].schedule_time は HH:MM（24 時間表記）で指定してください")

        image_path = PurePosixPath(self.image)
        if not self.image or image_path.is_absolute() or ".." in image_path.parts:
            raise ConfigError("community_draft.posts[].image は collection 内の安全な相対パスで指定してください")


@dataclass(frozen=True)
class CommunityDraft:
    """`community_draft` セクション（optional）."""

    variables: dict[str, str] = field(default_factory=dict)
    posts: tuple[CommunityDraftPost, ...] = ()
