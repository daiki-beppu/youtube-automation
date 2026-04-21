"""プレイリスト設定の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Playlists:
    """`playlists` セクション（optional）.

    `items` は `{"playlist_key": "playlist_id", ...}` 形式の dict.
    """

    items: dict[str, str] = field(default_factory=dict)
