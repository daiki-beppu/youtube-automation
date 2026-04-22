"""
トラフィックソース分析 Mixin
YouTubeAnalyticsCollector のトラフィック流入元分析メソッド群
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List

from googleapiclient.errors import HttpError

if TYPE_CHECKING:
    from .analytics_base import AnalyticsBase  # noqa: F401


logger = logging.getLogger(__name__)


class TrafficSourceMixin:
    """トラフィックソース（流入元）分析"""

    def get_traffic_source_analytics(self, start_date: str, end_date: str) -> Dict:
        """
        チャンネル全体のトラフィックソース分析

        Args:
            start_date (str): 開始日
            end_date (str): 終了日

        Returns:
            Dict: トラフィックソース別の views/watch_time
        """
        if not self.analytics_service:
            self.initialize()

        logger.info("トラフィックソース分析実行中...")

        try:
            response = (
                self.analytics_service.reports()
                .query(
                    ids=f"channel=={self.channel_id}",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views,estimatedMinutesWatched,averageViewDuration",
                    dimensions="insightTrafficSourceType",
                    sort="-views",
                )
                .execute()
            )

            sources = {}
            if "rows" in response:
                for row in response["rows"]:
                    sources[row[0]] = {
                        "views": row[1],
                        "watch_time_minutes": row[2],
                        "avg_view_duration": row[3],
                    }

            # 合計からシェアを計算
            total_views = sum(s["views"] for s in sources.values())
            for source_data in sources.values():
                source_data["view_share_percent"] = (
                    round((source_data["views"] / total_views) * 100, 1) if total_views > 0 else 0
                )

            logger.info(f"トラフィックソース: {len(sources)} タイプ検出")
            return {
                "sources": sources,
                "total_views": total_views,
            }

        except HttpError as e:
            logger.error(f"YouTube API エラー（トラフィックソース）: {e}")
            return {"sources": {}, "total_views": 0, "error": str(e)}
        except Exception as e:
            logger.error(f"トラフィックソース分析エラー: {e}")
            return {"sources": {}, "total_views": 0, "error": str(e)}

    def get_traffic_source_detail(self, start_date: str, end_date: str, source_type: str) -> List[Dict]:
        """
        特定トラフィックソースの詳細取得（例: YT_SEARCH の検索キーワード）

        Args:
            start_date (str): 開始日
            end_date (str): 終了日
            source_type (str): トラフィックソースタイプ（例: 'YT_SEARCH', 'EXT_URL'）

        Returns:
            List[Dict]: 詳細データ
        """
        if not self.analytics_service:
            self.initialize()

        logger.info(f"トラフィックソース詳細取得: {source_type}")

        try:
            response = (
                self.analytics_service.reports()
                .query(
                    ids=f"channel=={self.channel_id}",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views,estimatedMinutesWatched",
                    dimensions="insightTrafficSourceDetail",
                    filters=f"insightTrafficSourceType=={source_type}",
                    sort="-views",
                    maxResults=25,
                )
                .execute()
            )

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

        except HttpError as e:
            logger.error(f"YouTube API エラー（トラフィック詳細 {source_type}）: {e}")
            return []
        except Exception as e:
            logger.error(f"トラフィック詳細取得エラー: {e}")
            return []
