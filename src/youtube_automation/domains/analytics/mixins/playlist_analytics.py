"""
プレイリスト経由視聴分析 Mixin
YouTubeAnalyticsCollector のプレイリスト別分析メソッド群
"""

from __future__ import annotations

import logging
from typing import Dict

from youtube_automation.utils.exceptions import YouTubeAPIError

logger = logging.getLogger(__name__)


class PlaylistAnalyticsMixin:
    """上位 200 件のプレイリスト内視聴を分析する。"""

    def get_playlist_analytics(self, start_date: str, end_date: str) -> Dict:
        """上位 200 件のプレイリスト内 views と平均視聴時間を取得する。

        ``view_share_percent`` は API が返す上位 200 件内でのシェアであり、
        チャンネル全体に対するシェアではない。
        """
        logger.info("プレイリスト別分析実行中...")

        try:
            request = self.analytics_service.query(
                ids=f"channel=={self.channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="playlistViews,playlistAverageViewDuration",
                dimensions="playlist",
                sort="-playlistViews",
                maxResults=200,
            )
            response = request

            playlists = {}
            for row in response.get("rows", []):
                playlists[row[0]] = {
                    "views": row[1],
                    "average_view_duration": row[2],
                }

            total_views = sum(playlist["views"] for playlist in playlists.values())
            for playlist in playlists.values():
                playlist["view_share_percent"] = (
                    round((playlist["views"] / total_views) * 100, 1) if total_views > 0 else 0
                )

            logger.info("プレイリスト別: %s 件検出", len(playlists))
            return {"playlists": playlists, "total_views": total_views}

        except YouTubeAPIError as api_error:
            logger.exception(
                "YouTube API エラー（プレイリスト分析）: %s (status=%s)",
                api_error,
                api_error.status_code,
            )
            raise
