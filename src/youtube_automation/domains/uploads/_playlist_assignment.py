"""アップロード後のプレイリスト自動割り当てロジック。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from youtube_automation.configuration import load_config
from youtube_automation.domains.uploads.playlists import PlaylistManager
from youtube_automation.infrastructure.errors import ConfigError, YouTubeAPIError
from youtube_automation.infrastructure.filesystem import path_exists, read_file_text
from youtube_automation.infrastructure.google.upload import HttpError
from youtube_automation.utils.collection_paths import CollectionPaths

logger = logging.getLogger(__name__)


class PlaylistAssignmentMixin:
    """アップロード後にプレイリストへ自動追加する mixin。"""

    def _assign_to_playlists(self, video_id: str, collection_path: Path):
        """アップロード後にプレイリストへ自動追加（失敗してもアップロードはブロックしない）"""
        ws_path = CollectionPaths(collection_path).workflow_state_path
        if not path_exists(ws_path):
            return

        ws = json.loads(read_file_text(ws_path))

        theme = ws.get("theme", "")
        if not theme:
            return

        config = load_config()
        if not config.playlists.items:
            return

        try:
            clients = self.youtube_clients
            pm = PlaylistManager(clients=clients)
            assigned = pm.assign_video(video_id, theme, collection_path=collection_path)
            if assigned:
                logger.info(f"📋 プレイリスト追加: {assigned}")
        except (ConfigError, YouTubeAPIError, HttpError) as e:
            logger.warning(f"⚠️  プレイリスト追加エラー（非致命的）: {e}")


__all__ = ["PlaylistAssignmentMixin"]
