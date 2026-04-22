"""動画 × 日次データ取得 Mixin（launch curve 分析用）"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class VideoDailyAnalyticsMixin:
    """動画 × 日次粒度で views を取得する

    動画×日次では `videoThumbnailImpressions*` が API 仕様上取得不可のため views のみ。
    impressions/CTR は `ChannelDailyAnalyticsMixin.get_channel_daily_impressions` で代替する。
    """

    def get_video_daily_analytics(
        self,
        start_date: str,
        end_date: str,
        video_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        dimensions='video,day' で日次 views を取得する。

        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            video_ids: 対象動画 ID リスト（None で全動画。API 上限に注意）

        Returns:
            List[Dict]: [{video_id, date, views}, ...]
        """
        if not self.analytics_service:
            self.initialize()  # type: ignore[attr-defined]

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

        response = (
            self.analytics_service.reports()
            .query(
                metrics="views",
                **query_kwargs,
            )
            .execute()
        )
        return self._parse_video_daily_rows(response)

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
        ]
