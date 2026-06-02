"""アップロード後のプレイリスト自動割り当てロジック。

責務分割（Issue #465）の一環で ``collection_uploader.py`` から分離した。
``PlaylistManager`` / ``load_config`` への参照は本 mixin 内に保持されるが、
``collection_uploader`` モジュールでも従来通り再エクスポートする
（既存テストが ``patch("youtube_automation.agents.collection_uploader.PlaylistManager")``
で差し替えるための後方互換）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from googleapiclient.errors import HttpError

from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.exceptions import ConfigError, YouTubeAPIError

logger = logging.getLogger(__name__)


class PlaylistAssignmentMixin:
    """アップロード後にプレイリストへ自動追加する mixin。"""

    def _assign_to_playlists(self, video_id: str, collection_path: Path):
        """アップロード後にプレイリストへ自動追加（失敗してもアップロードはブロックしない）"""
        ws_path = CollectionPaths(collection_path).workflow_state_path
        if not ws_path.exists():
            return

        with open(ws_path, "r", encoding="utf-8") as f:
            ws = json.load(f)

        theme = ws.get("theme", "")
        if not theme:
            return

        # 後方互換のため、PlaylistManager / load_config は collection_uploader 経由で解決する。
        # 既存テストは collection_uploader.PlaylistManager / load_config を直接 patch するため、
        # ここで遅延 import することで mock を尊重する。
        from youtube_automation.agents import collection_uploader

        config = collection_uploader.load_config()
        if not config.playlists.items:
            return

        try:
            pm = collection_uploader.PlaylistManager()
            assigned = pm.assign_video(video_id, theme, collection_path=collection_path)
            if assigned:
                logger.info(f"📋 プレイリスト追加: {assigned}")
        except (ConfigError, YouTubeAPIError, HttpError) as e:
            logger.warning(f"⚠️  プレイリスト追加エラー（非致命的）: {e}")


__all__ = ["PlaylistAssignmentMixin"]
