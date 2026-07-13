"""
オーディエンス分析 Mixin
YouTubeAnalyticsCollector のデバイス別・地域別分析メソッド群
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict

from youtube_automation.utils.exceptions import YouTubeAPIError
from youtube_automation.utils.retry import execute_with_retry

if TYPE_CHECKING:
    from .analytics_base import AnalyticsBase  # noqa: F401


logger = logging.getLogger(__name__)


class AudienceAnalyticsMixin:
    """デバイス別・地域別のオーディエンス分析"""

    def get_device_analytics(self, start_date: str, end_date: str) -> Dict:
        """
        デバイス別分析

        Args:
            start_date (str): 開始日
            end_date (str): 終了日

        Returns:
            Dict: デバイスタイプ別の views/watch_time
        """
        if not self.analytics_service:
            self.initialize()

        logger.info("デバイス別分析実行中...")

        try:
            request = self.analytics_service.reports().query(
                ids=f"channel=={self.channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="views,estimatedMinutesWatched,averageViewDuration",
                dimensions="deviceType",
                sort="-views",
            )
            response = execute_with_retry(request, "YouTube Analytics API request failed")

            devices = {}
            if "rows" in response:
                for row in response["rows"]:
                    devices[row[0]] = {
                        "views": row[1],
                        "watch_time_minutes": row[2],
                        "avg_view_duration": row[3],
                    }

            total_views = sum(d["views"] for d in devices.values())
            for device_data in devices.values():
                device_data["view_share_percent"] = (
                    round((device_data["views"] / total_views) * 100, 1) if total_views > 0 else 0
                )

            logger.info(f"デバイス別: {len(devices)} タイプ検出")
            return {
                "devices": devices,
                "total_views": total_views,
            }

        except YouTubeAPIError as e:
            logger.error(f"YouTube API エラー（デバイス分析）: {e}")
            return {"devices": {}, "total_views": 0, "error": str(e)}
        except Exception as e:
            logger.error(f"デバイス分析エラー: {e}")
            return {"devices": {}, "total_views": 0, "error": str(e)}

    def get_country_analytics(self, start_date: str, end_date: str, max_countries: int = 20) -> Dict:
        """
        地域別分析

        Args:
            start_date (str): 開始日
            end_date (str): 終了日
            max_countries (int): 取得する国数の上限

        Returns:
            Dict: 国別の views/watch_time/subscribers
        """
        if not self.analytics_service:
            self.initialize()

        logger.info("地域別分析実行中...")

        try:
            request = self.analytics_service.reports().query(
                ids=f"channel=={self.channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained",
                dimensions="country",
                sort="-views",
                maxResults=max_countries,
            )
            response = execute_with_retry(request, "YouTube Analytics API request failed")

            countries = {}
            if "rows" in response:
                for row in response["rows"]:
                    countries[row[0]] = {
                        "views": row[1],
                        "watch_time_minutes": row[2],
                        "avg_view_duration": row[3],
                        "subscribers_gained": row[4],
                    }

            total_views = sum(c["views"] for c in countries.values())
            for country_data in countries.values():
                country_data["view_share_percent"] = (
                    round((country_data["views"] / total_views) * 100, 1) if total_views > 0 else 0
                )

            logger.info(f"地域別: {len(countries)} カ国検出")
            return {
                "countries": countries,
                "total_views": total_views,
            }

        except YouTubeAPIError as e:
            logger.error(f"YouTube API エラー（地域分析）: {e}")
            return {"countries": {}, "total_views": 0, "error": str(e)}
        except Exception as e:
            logger.error(f"地域分析エラー: {e}")
            return {"countries": {}, "total_views": 0, "error": str(e)}
