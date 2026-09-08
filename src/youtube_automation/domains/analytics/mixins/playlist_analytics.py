"""
プレイリスト経由視聴分析 Mixin
YouTubeAnalyticsCollector のプレイリスト別分析メソッド群
"""

from __future__ import annotations

import logging
from typing import Dict

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.analytics.breakdowns import collect_view_breakdown
from youtube_automation.domains.analytics.ports import AnalyticsClient

logger = logging.getLogger(__name__)


def collect_playlist_analytics(
    analytics_client: AnalyticsClient, channel_id: str | None, start_date: str, end_date: str
) -> Dict:
    """上位 200 件のプレイリスト内 views と平均視聴時間を取得する。

    ``view_share_percent`` は API が返す上位 200 件内でのシェアであり、
    チャンネル全体に対するシェアではない。
    """
    logger.info("プレイリスト別分析実行中...")

    try:
        playlists, total_views = collect_view_breakdown(
            analytics_client,
            channel_id,
            start_date,
            end_date,
            dimension="playlist",
            fields=("views", "average_view_duration"),
            metrics="playlistViews,playlistAverageViewDuration",
            sort="-playlistViews",
            maxResults=200,
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


class PlaylistAnalyticsMixin:
    """Compatibility adapter for collectors assembled with mixins."""

    analytics_service: AnalyticsClient
    channel_id: str | None

    def get_playlist_analytics(self, start_date: str, end_date: str) -> Dict:
        return collect_playlist_analytics(self.analytics_service, self.channel_id, start_date, end_date)
