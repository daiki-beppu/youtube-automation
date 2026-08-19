"""YouTube Analytics API の収益メトリクス収集。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.analytics.query_contract import TARGETED_QUERY_VIEWS_METRIC

if TYPE_CHECKING:
    from youtube_automation.domains.analytics.ports import AnalyticsBase  # noqa: F401

logger = logging.getLogger(__name__)

_DAILY_REVENUE_METRICS = (
    f"{TARGETED_QUERY_VIEWS_METRIC},estimatedRevenue,monetizedPlaybacks,adImpressions,cpm,playbackBasedCpm"
)
_VIDEO_REVENUE_METRICS = f"{TARGETED_QUERY_VIEWS_METRIC},estimatedRevenue,monetizedPlaybacks,cpm,playbackBasedCpm"
_VIDEO_REVENUE_MAX_RESULTS = 200


class RevenueAnalyticsMixin:
    """収益化済みチャンネルで利用可能な monetary metrics を収集する。"""

    def get_revenue_analytics(self, start_date: str, end_date: str) -> dict[str, object]:
        """日別・動画別の収益メトリクスを取得する。

        monetary データにアクセスできないチャンネルでは警告して空データを返す。
        収益取得を基本メトリクスと別クエリにすることで、収益化状態が既存収集を
        失敗させないようにしている。
        """
        daily_response, daily_error = self._get_daily_revenue(start_date, end_date)
        video_response, video_error = self._get_video_revenue(start_date, end_date)
        errors = {
            dimension: str(error)
            for dimension, error in (("day", daily_error), ("video", video_error))
            if error is not None
        }

        if daily_response is None and video_response is None:
            return {
                "status": "unavailable",
                "reason": "; ".join(f"{dimension}: {reason}" for dimension, reason in errors.items()),
                "errors": errors,
                "daily_metrics": [],
                "by_video": {},
                "summary": {},
            }

        daily_metrics = (
            [self._daily_revenue_row(row) for row in daily_response.get("rows", [])]
            if daily_response is not None
            else []
        )
        by_video = (
            {row[0]: self._video_revenue_row(row) for row in video_response.get("rows", [])}
            if video_response is not None
            else {}
        )
        result: dict[str, object] = {
            "status": "partial" if errors else "available",
            "currency": self._revenue_currency(daily_response, video_response),
            "daily_metrics": daily_metrics,
            "by_video": by_video,
            "summary": self._revenue_summary(daily_metrics) if daily_response is not None else {},
        }
        if errors:
            result["errors"] = errors
        return result

    def _get_daily_revenue(
        self, start_date: str, end_date: str
    ) -> tuple[dict[str, object] | None, YouTubeAPIError | None]:
        """日次収益を取得し、失敗情報を動画別クエリから隔離する。"""
        try:
            return (
                self.analytics_service.query(
                    ids=f"channel=={self.channel_id}",
                    startDate=start_date,
                    endDate=end_date,
                    metrics=_DAILY_REVENUE_METRICS,
                    dimensions="day",
                ),
                None,
            )
        except YouTubeAPIError as error:
            logger.warning(
                "日次収益メトリクスを取得できません。基本メトリクスの収集は継続します: %s",
                error,
            )
            return None, error

    def _get_video_revenue(
        self, start_date: str, end_date: str
    ) -> tuple[dict[str, object] | None, YouTubeAPIError | None]:
        """動画別収益を取得し、失敗情報を日次クエリから隔離する。"""
        try:
            return (
                self.analytics_service.query(
                    ids=f"channel=={self.channel_id}",
                    startDate=start_date,
                    endDate=end_date,
                    metrics=_VIDEO_REVENUE_METRICS,
                    dimensions="video",
                    sort="-estimatedRevenue",
                    maxResults=_VIDEO_REVENUE_MAX_RESULTS,
                ),
                None,
            )
        except YouTubeAPIError as error:
            logger.warning(
                "動画別収益メトリクスを取得できません。基本メトリクスの収集は継続します: %s",
                error,
            )
            return None, error

    @staticmethod
    def _revenue_currency(daily_response: dict[str, object] | None, video_response: dict[str, object] | None) -> object:
        """成功した収益レスポンスから通貨を返す。"""
        if daily_response is not None:
            return daily_response.get("currency")
        if video_response is not None:
            return video_response.get("currency")
        raise ValueError("収益レスポンスがありません")

    @staticmethod
    def _revenue_summary(daily_metrics: list[dict[str, str | int | float]]) -> dict[str, int | float]:
        """日次収益から期間集計を算出する。"""
        total_views = sum(int(row["views"]) for row in daily_metrics)
        total_revenue = sum(float(row["estimated_revenue"]) for row in daily_metrics)
        return {
            "estimated_revenue": total_revenue,
            "monetized_playbacks": sum(int(row["monetized_playbacks"]) for row in daily_metrics),
            "views": total_views,
            "rpm": RevenueAnalyticsMixin._calculate_rpm(total_revenue, total_views),
        }

    @staticmethod
    def _daily_revenue_row(row: list[object]) -> dict[str, str | int | float]:
        """日次の monetary metrics を安定したキーへ変換する。"""
        dimension = str(row[0])
        views = int(row[1])
        estimated_revenue = float(row[2])
        monetized_playbacks = int(row[3])
        ad_impressions = int(row[4])
        return {
            "date": dimension,
            "views": views,
            "estimated_revenue": estimated_revenue,
            "monetized_playbacks": monetized_playbacks,
            "ad_impressions": ad_impressions,
            "ads_per_playback": RevenueAnalyticsMixin._calculate_ads_per_playback(ad_impressions, monetized_playbacks),
            "cpm": float(row[5]),
            "playback_based_cpm": float(row[6]),
            "rpm": RevenueAnalyticsMixin._calculate_rpm(estimated_revenue, views),
        }

    @staticmethod
    def _video_revenue_row(row: list[object]) -> dict[str, str | int | float]:
        """動画別の monetary metrics を安定したキーへ変換する。"""
        views = int(row[1])
        estimated_revenue = float(row[2])
        return {
            "video_id": str(row[0]),
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

    @staticmethod
    def _calculate_ads_per_playback(ad_impressions: int, monetized_playbacks: int) -> float:
        return ad_impressions / monetized_playbacks if monetized_playbacks else 0.0
