"""アップロード後のプレイリスト自動割り当てロジック。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from youtube_automation.configuration import ChannelConfig, load_config
from youtube_automation.core.adapters.media import CollectionPaths
from youtube_automation.domains.uploads.playlists import PlaylistManager
from youtube_automation.infrastructure.filesystem import path_exists, read_file_text
from youtube_automation.infrastructure.google.youtube import YouTubeClients

logger = logging.getLogger(__name__)


class PlaylistAssignment:
    """YouTube clients を明示的に受けて動画をプレイリストへ割り当てる。"""

    def __init__(
        self,
        youtube_clients: YouTubeClients | None,
        config: ChannelConfig | None = None,
        playlist_manager: PlaylistManager | None = None,
    ) -> None:
        self.youtube_clients = youtube_clients
        self.config = config
        self.playlist_manager = playlist_manager

    def assign(self, video_id: str, collection_path: Path) -> None:
        """アップロード後にプレイリストへ自動追加する。"""
        ws_path = CollectionPaths(collection_path).workflow_state_path
        if not path_exists(ws_path):
            return

        ws = json.loads(read_file_text(ws_path))

        theme = ws.get("theme", "")
        if not theme:
            return

        config = self.config if self.config is not None else load_config()
        if not config.playlists.items:
            return

        pm = (
            self.playlist_manager
            if self.playlist_manager is not None
            else PlaylistManager(clients=self.youtube_clients)
        )
        assigned = pm.assign_video(video_id, theme, collection_path=collection_path)
        if assigned:
            logger.info(f"📋 プレイリスト追加: {assigned}")


__all__ = ["PlaylistAssignment"]
