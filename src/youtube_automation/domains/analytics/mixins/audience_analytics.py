"""
オーディエンス分析 Mixin
YouTubeAnalyticsCollector のデバイス別・地域別分析メソッド群
"""

from __future__ import annotations

import logging
from typing import Dict

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.analytics.breakdowns import DEFAULT_VIEW_FIELDS, collect_view_breakdown
from youtube_automation.domains.analytics.ports import AnalyticsClient
from youtube_automation.domains.analytics.query_contract import (
    TARGETED_QUERY_VIEWS_METRIC,
)

logger = logging.getLogger(__name__)


def _audience_report(
    analytics_client: AnalyticsClient,
    channel_id: str | None,
    start_date: str,
    end_date: str,
    *,
    dimension: str,
    result_key: str,
    label: str,
    count_unit: str,
    **query: object,
) -> Dict:
    """Build the common audience report, including its fail-soft API error result."""
    logger.info(f"{label}別分析実行中...")
    try:
        categories, total_views = collect_view_breakdown(
            analytics_client, channel_id, start_date, end_date, dimension=dimension, **query
        )
        logger.info(f"{label}別: {len(categories)} {count_unit}検出")
        return {result_key: categories, "total_views": total_views}
    except YouTubeAPIError as error:
        logger.error(f"YouTube API エラー（{label}分析）: {error}")
        return {result_key: {}, "total_views": 0, "error": str(error)}


def collect_subscribed_status_analytics(
    analytics_client: AnalyticsClient, channel_id: str | None, start_date: str, end_date: str
) -> Dict:
    """登録済み・未登録視聴者別の視聴データを取得する。"""
    return _audience_report(
        analytics_client,
        channel_id,
        start_date,
        end_date,
        dimension="subscribedStatus",
        result_key="statuses",
        label="登録ステータス",
        count_unit="区分",
    )


def collect_device_analytics(
    analytics_client: AnalyticsClient, channel_id: str | None, start_date: str, end_date: str
) -> Dict:
    """
    デバイス別分析

    Args:
        start_date (str): 開始日
        end_date (str): 終了日

    Returns:
        Dict: デバイスタイプ別の views/watch_time
    """
    return _audience_report(
        analytics_client,
        channel_id,
        start_date,
        end_date,
        dimension="deviceType",
        result_key="devices",
        label="デバイス",
        count_unit="タイプ",
    )


def collect_country_analytics(
    analytics_client: AnalyticsClient, channel_id: str | None, start_date: str, end_date: str, max_countries: int = 20
) -> Dict:
    """
    地域別分析

    Args:
        start_date (str): 開始日
        end_date (str): 終了日
        max_countries (int): 取得する国数の上限

    Returns:
        Dict: 国別の views/watch_time/subscribers
    """
    return _audience_report(
        analytics_client,
        channel_id,
        start_date,
        end_date,
        dimension="country",
        result_key="countries",
        label="地域",
        count_unit="カ国",
        fields=(*DEFAULT_VIEW_FIELDS, "subscribers_gained"),
        metrics=f"{TARGETED_QUERY_VIEWS_METRIC},estimatedMinutesWatched,averageViewDuration,subscribersGained",
        maxResults=max_countries,
    )


class AudienceAnalyticsMixin:
    """Compatibility adapter for collectors assembled with mixins."""

    analytics_service: AnalyticsClient
    channel_id: str | None

    def get_subscribed_status_analytics(self, start_date: str, end_date: str) -> Dict:
        return collect_subscribed_status_analytics(self.analytics_service, self.channel_id, start_date, end_date)

    def get_device_analytics(self, start_date: str, end_date: str) -> Dict:
        return collect_device_analytics(self.analytics_service, self.channel_id, start_date, end_date)

    def get_country_analytics(self, start_date: str, end_date: str, max_countries: int = 20) -> Dict:
        return collect_country_analytics(self.analytics_service, self.channel_id, start_date, end_date, max_countries)
