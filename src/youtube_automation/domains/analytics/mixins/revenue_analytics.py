"""YouTube Analytics API の収益メトリクス収集。"""

from __future__ import annotations

import logging

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.analytics.ports import AnalyticsClient
from youtube_automation.domains.analytics.query_contract import TARGETED_QUERY_VIEWS_METRIC

logger = logging.getLogger(__name__)

_DAILY_REVENUE_METRICS = (
    f"{TARGETED_QUERY_VIEWS_METRIC},estimatedRevenue,monetizedPlaybacks,adImpressions,cpm,playbackBasedCpm"
)
_VIDEO_REVENUE_METRICS = f"{TARGETED_QUERY_VIEWS_METRIC},estimatedRevenue,monetizedPlaybacks,cpm,playbackBasedCpm"
_VIDEO_REVENUE_MAX_RESULTS = 200


def collect_revenue_analytics(
    analytics_client: AnalyticsClient, channel_id: str | None, start_date: str, end_date: str
) -> dict[str, object]:
    """日別・動画別の収益メトリクスを取得する。

    monetary データにアクセスできないチャンネルでは警告して空データを返す。
    収益取得を基本メトリクスと別クエリにすることで、収益化状態が既存収集を
    失敗させないようにしている。
    """
    daily_response, daily_error = _query_revenue(
        analytics_client,
        channel_id,
        start_date,
        end_date,
        label="日次",
        metrics=_DAILY_REVENUE_METRICS,
        dimensions="day",
    )
    video_response, video_error = _query_revenue(
        analytics_client,
        channel_id,
        start_date,
        end_date,
        label="動画別",
        metrics=_VIDEO_REVENUE_METRICS,
        dimensions="video",
        sort="-estimatedRevenue",
        maxResults=_VIDEO_REVENUE_MAX_RESULTS,
    )
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
        [_daily_revenue_row(row) for row in daily_response.get("rows", [])] if daily_response is not None else []
    )
    by_video = (
        {row[0]: _video_revenue_row(row) for row in video_response.get("rows", [])}
        if video_response is not None
        else {}
    )
    result: dict[str, object] = {
        "status": "partial" if errors else "available",
        "currency": _revenue_currency(daily_response, video_response),
        "daily_metrics": daily_metrics,
        "by_video": by_video,
        "summary": _revenue_summary(daily_metrics) if daily_response is not None else {},
    }
    if errors:
        result["errors"] = errors
    return result


def _query_revenue(
    analytics_client: AnalyticsClient,
    channel_id: str | None,
    start_date: str,
    end_date: str,
    *,
    label: str,
    **query: object,
) -> tuple[dict[str, object] | None, YouTubeAPIError | None]:
    """Execute one revenue query without suppressing another query's outcome."""
    try:
        return (
            analytics_client.query(ids=f"channel=={channel_id}", startDate=start_date, endDate=end_date, **query),
            None,
        )
    except YouTubeAPIError as error:
        logger.warning(
            "%s収益メトリクスを取得できません。基本メトリクスの収集は継続します: %s",
            label,
            error,
        )
        return None, error


def _revenue_currency(daily_response: dict[str, object] | None, video_response: dict[str, object] | None) -> object:
    """成功した収益レスポンスから通貨を返す。"""
    if daily_response is not None:
        return daily_response.get("currency")
    if video_response is not None:
        return video_response.get("currency")
    raise ValueError("収益レスポンスがありません")


def _revenue_summary(daily_metrics: list[dict[str, str | int | float]]) -> dict[str, int | float]:
    """日次収益から期間集計を算出する。"""
    total_views = sum(int(row["views"]) for row in daily_metrics)
    total_revenue = sum(float(row["estimated_revenue"]) for row in daily_metrics)
    return {
        "estimated_revenue": total_revenue,
        "monetized_playbacks": sum(int(row["monetized_playbacks"]) for row in daily_metrics),
        "views": total_views,
        "rpm": _calculate_rpm(total_revenue, total_views),
    }


def _revenue_row_metrics(row: list[object], *, cpm_index: int) -> dict[str, int | float]:
    """Normalize monetary columns shared by daily and video query results."""
    views = int(row[1])
    estimated_revenue = float(row[2])
    return {
        "views": views,
        "estimated_revenue": estimated_revenue,
        "monetized_playbacks": int(row[3]),
        "cpm": float(row[cpm_index]),
        "playback_based_cpm": float(row[cpm_index + 1]),
        "rpm": _calculate_rpm(estimated_revenue, views),
    }


def _daily_revenue_row(row: list[object]) -> dict[str, str | int | float]:
    """日次の monetary metrics を安定したキーへ変換する。"""
    metrics = _revenue_row_metrics(row, cpm_index=5)
    ad_impressions = int(row[4])
    return {
        "date": str(row[0]),
        **metrics,
        "ad_impressions": ad_impressions,
        "ads_per_playback": _calculate_ads_per_playback(ad_impressions, int(metrics["monetized_playbacks"])),
    }


def _video_revenue_row(row: list[object]) -> dict[str, str | int | float]:
    """動画別の monetary metrics を安定したキーへ変換する。"""
    return {"video_id": str(row[0]), **_revenue_row_metrics(row, cpm_index=4)}


def _calculate_rpm(estimated_revenue: float, views: int) -> float:
    return estimated_revenue / views * 1000 if views else 0.0


def _calculate_ads_per_playback(ad_impressions: int, monetized_playbacks: int) -> float:
    return ad_impressions / monetized_playbacks if monetized_playbacks else 0.0


class RevenueAnalyticsMixin:
    """Compatibility entry point for callers assembling their own collector."""

    analytics_service: AnalyticsClient
    channel_id: str | None

    def get_revenue_analytics(self, start_date: str, end_date: str) -> dict[str, object]:
        return collect_revenue_analytics(self.analytics_service, self.channel_id, start_date, end_date)
