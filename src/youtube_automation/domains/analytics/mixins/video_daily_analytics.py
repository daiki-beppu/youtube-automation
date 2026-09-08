"""動画 × 日次データ取得 Mixin（launch curve 分析用）"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Dict, List, Optional

from youtube_automation.core.adapters.observability import section
from youtube_automation.domains.analytics.ports import AnalyticsClient
from youtube_automation.domains.analytics.query_contract import TARGETED_QUERY_VIEWS_METRIC

logger = logging.getLogger(__name__)


def parse_video_daily_rows(response: Dict) -> List[Dict]:
    rows = response.get("rows", [])
    return [
        {
            "video_id": row[0],
            "date": row[1],
            "views": row[2],
        }
        for row in rows
        if len(row) >= 3
    ]


def collect_video_daily_analytics(
    analytics_client: AnalyticsClient,
    channel_id: str | None,
    start_date: str,
    end_date: str,
    video_ids: Optional[List[str]] = None,
    *,
    parse_rows: Callable[[Dict], List[Dict]] = parse_video_daily_rows,
) -> List[Dict]:
    """Query video/day engaged views and convert the returned rows."""
    query_kwargs = {
        "ids": f"channel=={channel_id}",
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": "video,day",
        "sort": "day",
        "maxResults": 10000,
    }
    if video_ids:
        query_kwargs["filters"] = "video==" + ",".join(video_ids)

    with section(
        "video_daily.query",
        days=(start_date, end_date),
        filtered=bool(video_ids),
    ):
        request = analytics_client.query(
            metrics=TARGETED_QUERY_VIEWS_METRIC,
            **query_kwargs,
        )
        response = request
    rows = parse_rows(response)
    logger.debug("video_daily rows=%d", len(rows))
    return rows


class VideoDailyAnalyticsMixin:
    """Compatibility adapter preserving the daily-response parser override."""

    analytics_service: AnalyticsClient
    channel_id: str | None
    _parse_video_daily_rows = staticmethod(parse_video_daily_rows)

    def get_video_daily_analytics(
        self, start_date: str, end_date: str, video_ids: Optional[List[str]] = None
    ) -> List[Dict]:
        return collect_video_daily_analytics(
            self.analytics_service,
            self.channel_id,
            start_date,
            end_date,
            video_ids,
            parse_rows=self._parse_video_daily_rows,
        )
