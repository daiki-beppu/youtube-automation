"""YouTube Analytics API の収益メトリクス収集。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from youtube_automation.infrastructure.errors import YouTubeAPIError
from youtube_automation.infrastructure.retry import execute_with_retry

if TYPE_CHECKING:
    from .analytics_base import AnalyticsBase  # noqa: F401

logger = logging.getLogger(__name__)

_REVENUE_METRICS = "views,estimatedRevenue,monetizedPlaybacks,cpm,playbackBasedCpm"


class RevenueAnalyticsMixin:
    """収益化済みチャンネルで利用可能な monetary metrics を収集する。"""

    def get_revenue_analytics(self, start_date: str, end_date: str) -> dict[str, object]:
        """日別・動画別の収益メトリクスを取得する。

        monetary データにアクセスできないチャンネルでは警告して空データを返す。
        収益取得を基本メトリクスと別クエリにすることで、収益化状態が既存収集を
        失敗させないようにしている。
        """
        if not self.analytics_service:
            self.initialize()

        try:
            daily_request = self.analytics_service.reports().query(
                ids=f"channel=={self.channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics=_REVENUE_METRICS,
                dimensions="day",
            )
            daily_response = execute_with_retry(daily_request, "YouTube Analytics revenue daily request failed")

            video_request = self.analytics_service.reports().query(
                ids=f"channel=={self.channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics=_REVENUE_METRICS,
                dimensions="video",
                sort="-estimatedRevenue",
            )
            video_response = execute_with_retry(video_request, "YouTube Analytics revenue video request failed")
        except YouTubeAPIError as error:
            logger.warning(
                "収益メトリクスを取得できないため skip します。基本メトリクスの収集は継続します: %s",
                error,
            )
            return {
                "status": "unavailable",
                "reason": str(error),
                "daily_metrics": [],
                "by_video": {},
                "summary": {},
            }

        daily_metrics = [self._revenue_row(row, dimension_key="date") for row in daily_response.get("rows", [])]
        by_video = {row[0]: self._revenue_row(row, dimension_key="video_id") for row in video_response.get("rows", [])}
        total_views = sum(row["views"] for row in daily_metrics)
        total_revenue = sum(row["estimated_revenue"] for row in daily_metrics)

        return {
            "status": "available",
            "currency": daily_response.get("currency"),
            "daily_metrics": daily_metrics,
            "by_video": by_video,
            "summary": {
                "estimated_revenue": total_revenue,
                "monetized_playbacks": sum(row["monetized_playbacks"] for row in daily_metrics),
                "views": total_views,
                "rpm": self._calculate_rpm(total_revenue, total_views),
            },
        }

    @staticmethod
    def _revenue_row(row: list[object], *, dimension_key: str) -> dict[str, str | int | float]:
        """dimension + monetary metrics の API row を安定したキーへ変換する。"""
        dimension = str(row[0])
        views = int(row[1])
        estimated_revenue = float(row[2])
        return {
            dimension_key: dimension,
            "views": views,
            "estimated_revenue": estimated_revenue,
            "monetized_playbacks": int(row[3]),
            "cpm": float(row[4]),
            "playback_based_cpm": float(row[5]),
            "rpm": RevenueAnalyticsMixin._calculate_rpm(estimated_revenue, views),
        }

    @staticmethod
    def _calculate_rpm(estimated_revenue: float, views: int) -> float:
        return estimated_revenue / views * 1000 if views else 0.0
