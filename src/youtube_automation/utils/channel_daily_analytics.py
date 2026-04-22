"""チャンネル × 日次 impressions/CTR 取得 Mixin"""

from __future__ import annotations

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class ChannelDailyAnalyticsMixin:
    """チャンネル × 日次粒度で views/impressions/CTR を取得する

    動画別 impressions が取れないため、チャンネル全体の日次値で代替する。
    Traffic Source Report は `day` を optional dimension として許容するため、
    `dimensions=insightTrafficSourceType,day` で取得し day ごとに合算して
    1 日 1 行に戻す（流入元内訳は `get_ctr_analysis` の impressions_summary 側で取得）。
    """

    def get_channel_daily_impressions(
        self,
        start_date: str,
        end_date: str,
    ) -> List[Dict]:
        """
        Traffic Source × day レポートで日次 views/impressions/CTR を取得する。

        Args:
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD

        Returns:
            List[Dict]: [{date, views, impressions, impression_ctr}, ...] （date 昇順）
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
                dimensions="insightTrafficSourceType,day",
                sort="day",
                maxResults=10000,
            )
            .execute()
        )
        return self._parse_channel_daily_rows(response)

    @staticmethod
    def _parse_channel_daily_rows(response: Dict) -> List[Dict]:
        """Traffic Source × day レスポンスを day ごとに合算する。

        row: [insightTrafficSourceType, date, views, impressions, impression_ctr]
        CTR は各行平均ではなく `sum(views) / sum(impressions)` で再計算。
        """
        rows = response.get("rows", [])
        by_date: Dict[str, Dict[str, float]] = {}

        for row in rows:
            date = row[1]
            views = row[2] if len(row) > 2 else 0
            impressions = row[3] if len(row) > 3 else 0

            agg = by_date.setdefault(date, {"views": 0, "impressions": 0})
            agg["views"] += views
            agg["impressions"] += impressions

        result: List[Dict] = []
        for date in sorted(by_date.keys()):
            agg = by_date[date]
            views = agg["views"]
            impressions = agg["impressions"]
            ctr = (views / impressions * 100) if impressions > 0 else 0
            result.append(
                {
                    "date": date,
                    "views": views,
                    "impressions": impressions,
                    "impression_ctr": round(ctr, 2),
                }
            )
        return result
