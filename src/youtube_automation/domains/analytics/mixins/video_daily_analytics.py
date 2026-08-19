"""動画 × 日次データ取得 Mixin（launch curve 分析用）"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from youtube_automation.core.adapters.observability import section
from youtube_automation.domains.analytics.query_contract import TARGETED_QUERY_VIEWS_METRIC

logger = logging.getLogger(__name__)


class VideoDailyAnalyticsMixin:
    """動画 × 日次粒度で engagedViews を取得して内部 views として返す。

    動画×日次では `videoThumbnailImpressions*` が API 仕様上取得不可のため engagedViews のみ。
    impressions/CTR は `ChannelDailyAnalyticsMixin.get_channel_daily_impressions` で代替する。
    """

    def get_video_daily_analytics(
        self,
        start_date: str,
        end_date: str,
        video_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        dimensions='video,day' で日次 engagedViews を取得する。

        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            video_ids: 対象動画 ID リスト（None で全動画。API 上限に注意）

        Returns:
            List[Dict]: [{video_id, date, views}, ...]
        """
        query_kwargs = {
            "ids": f"channel=={self.channel_id}",
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
            request = self.analytics_service.query(
                metrics=TARGETED_QUERY_VIEWS_METRIC,
                **query_kwargs,
            )
            response = request
        rows = self._parse_video_daily_rows(response)
        logger.debug("video_daily rows=%d", len(rows))
        return rows

    @staticmethod
    def _parse_video_daily_rows(response: Dict) -> List[Dict]:
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
