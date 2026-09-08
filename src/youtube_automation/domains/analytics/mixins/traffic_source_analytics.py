"""
トラフィックソース分析 Mixin
YouTubeAnalyticsCollector のトラフィック流入元分析メソッド群
"""

from __future__ import annotations

import logging
from typing import Dict, List

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.analytics.breakdowns import collect_view_breakdown
from youtube_automation.domains.analytics.ports import AnalyticsClient
from youtube_automation.domains.analytics.query_contract import (
    TARGETED_QUERY_VIEWS_METRIC,
    TARGETED_QUERY_VIEWS_SORT,
)

logger = logging.getLogger(__name__)


def collect_traffic_sources(
    analytics_client: AnalyticsClient, channel_id: str | None, start_date: str, end_date: str
) -> Dict:
    """
    チャンネル全体のトラフィックソース分析

    Args:
        start_date (str): 開始日
        end_date (str): 終了日

    Returns:
        Dict: トラフィックソース別の views/watch_time
    """
    logger.info("トラフィックソース分析実行中...")

    try:
        sources, total_views = collect_view_breakdown(
            analytics_client, channel_id, start_date, end_date, dimension="insightTrafficSourceType"
        )

        logger.info(f"トラフィックソース: {len(sources)} タイプ検出")
        return {
            "sources": sources,
            "total_views": total_views,
        }

    except YouTubeAPIError as e:
        logger.error(f"YouTube API エラー（トラフィックソース）: {e}")
        return {"sources": {}, "total_views": 0, "error": str(e)}


def collect_traffic_source_details(
    analytics_client: AnalyticsClient, channel_id: str | None, start_date: str, end_date: str, source_type: str
) -> List[Dict]:
    """
    特定トラフィックソースの詳細取得（例: YT_SEARCH の検索キーワード）

    Args:
        start_date (str): 開始日
        end_date (str): 終了日
        source_type (str): トラフィックソースタイプ（例: 'YT_SEARCH', 'EXT_URL'）

    Returns:
        List[Dict]: 詳細データ
    """
    logger.info(f"トラフィックソース詳細取得: {source_type}")

    try:
        request = analytics_client.query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics=f"{TARGETED_QUERY_VIEWS_METRIC},estimatedMinutesWatched",
            dimensions="insightTrafficSourceDetail",
            filters=f"insightTrafficSourceType=={source_type}",
            sort=TARGETED_QUERY_VIEWS_SORT,
            maxResults=25,
        )
        response = request

        details = []
        if "rows" in response:
            for row in response["rows"]:
                details.append(
                    {
                        "detail": row[0],
                        "views": row[1],
                        "watch_time_minutes": row[2],
                    }
                )

        logger.info(f"{source_type} 詳細: {len(details)} 件")
        return details

    except YouTubeAPIError as e:
        logger.error(f"YouTube API エラー（トラフィック詳細 {source_type}）: {e}")
        return []


class TrafficSourceMixin:
    """Compatibility adapter for collectors assembled with mixins."""

    analytics_service: AnalyticsClient
    channel_id: str | None

    def get_traffic_source_analytics(self, start_date: str, end_date: str) -> Dict:
        return collect_traffic_sources(self.analytics_service, self.channel_id, start_date, end_date)

    def get_traffic_source_detail(self, start_date: str, end_date: str, source_type: str) -> List[Dict]:
        return collect_traffic_source_details(
            self.analytics_service, self.channel_id, start_date, end_date, source_type
        )
