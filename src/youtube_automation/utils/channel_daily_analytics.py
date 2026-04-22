"""チャンネル × 日次 impressions/CTR 取得 Mixin"""

from __future__ import annotations

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class ChannelDailyAnalyticsMixin:
    """チャンネル × 日次粒度で views/impressions/CTR を取得する

    動画別 impressions が取れないため、チャンネル全体の日次値で代替する。
    """

    def get_channel_daily_impressions(
        self,
        start_date: str,
        end_date: str,
    ) -> List[Dict]:
        """
        dimensions='day' で日次 views/impressions/CTR を取得する。

        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD

        Returns:
            List[Dict]: [{date, views, impressions, impression_ctr}, ...]
        """
        if not self.analytics_service:
            self.initialize()  # type: ignore[attr-defined]

        response = (
            self.analytics_service.reports()
            .query(
                ids=f"channel=={self.channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="views,videoThumbnailImpressions,videoThumbnailImpressionsClickRate",
                dimensions="day",
                sort="day",
                maxResults=10000,
            )
            .execute()
        )
        return self._parse_channel_daily_rows(response)

    @staticmethod
    def _parse_channel_daily_rows(response: Dict) -> List[Dict]:
        rows = response.get("rows", [])
        return [
            {
                "date": row[0],
                "views": row[1],
                "impressions": row[2],
                "impression_ctr": row[3],
            }
            for row in rows
        ]
