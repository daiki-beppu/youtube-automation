"""
視聴維持率分析 Mixin
YouTubeAnalyticsCollector の視聴維持率（Retention）分析メソッド群
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List

from youtube_automation.utils.exceptions import YouTubeAPIError
from youtube_automation.utils.retry import execute_with_retry

if TYPE_CHECKING:
    from .analytics_base import AnalyticsBase  # noqa: F401


logger = logging.getLogger(__name__)


class RetentionAnalyticsMixin:
    """視聴維持率（Retention）分析"""

    def get_audience_retention(self, video_id: str, start_date: str, end_date: str) -> Dict:
        """
        特定動画の視聴維持率曲線を取得

        Args:
            video_id (str): 動画ID
            start_date (str): 開始日
            end_date (str): 終了日

        Returns:
            Dict: 視聴維持率データ（曲線 + サマリー）
        """
        if not self.analytics_service:
            self.initialize()

        try:
            request = self.analytics_service.reports().query(
                ids=f"channel=={self.channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="audienceWatchRatio,relativeRetentionPerformance",
                dimensions="elapsedVideoTimeRatio",
                filters=f"video=={video_id}",
                sort="elapsedVideoTimeRatio",
            )
            response = execute_with_retry(request, "YouTube Analytics API request failed")

            retention_curve = []
            if "rows" in response:
                for row in response["rows"]:
                    retention_curve.append(
                        {
                            "elapsed_ratio": row[0],
                            "watch_ratio": row[1],
                            "relative_performance": row[2],
                        }
                    )

            # サマリー統計を算出
            if retention_curve:
                watch_ratios = [p["watch_ratio"] for p in retention_curve]
                avg_retention = sum(watch_ratios) / len(watch_ratios)
                # 50% 地点の維持率
                midpoint = next((p for p in retention_curve if p["elapsed_ratio"] >= 0.5), None)
                midpoint_retention = midpoint["watch_ratio"] if midpoint else 0
            else:
                avg_retention = 0
                midpoint_retention = 0

            return {
                "video_id": video_id,
                "retention_curve": retention_curve,
                "average_retention": round(avg_retention, 4),
                "midpoint_retention": round(midpoint_retention, 4),
                "data_points": len(retention_curve),
            }

        except YouTubeAPIError as e:
            logger.warning(f"視聴維持率取得不可 (video={video_id}): {e}")
            return {
                "video_id": video_id,
                "retention_curve": [],
                "average_retention": 0,
                "midpoint_retention": 0,
                "data_points": 0,
                "error": str(e),
            }
        except Exception as e:
            logger.error(f"視聴維持率取得エラー (video={video_id}): {e}")
            return {
                "video_id": video_id,
                "retention_curve": [],
                "average_retention": 0,
                "midpoint_retention": 0,
                "data_points": 0,
                "error": str(e),
            }

    def get_retention_summary(self, start_date: str, end_date: str, top_n: int = 10) -> List[Dict]:
        """
        上位N本の動画の視聴維持率サマリーを取得

        Note: 動画ごとに1 API リクエストを消費するため、top_n でクォータを制御する。

        Args:
            start_date (str): 開始日
            end_date (str): 終了日
            top_n (int): 対象動画数（デフォルト10本）

        Returns:
            List[Dict]: 各動画の維持率サマリー
        """
        if not self.analytics_service:
            self.initialize()

        logger.info(f"視聴維持率サマリー取得: 上位 {top_n} 本")

        # 上位動画の video_id を取得
        try:
            request = self.analytics_service.reports().query(
                ids=f"channel=={self.channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="views",
                dimensions="video",
                sort="-views",
                maxResults=top_n,
            )
            response = execute_with_retry(request, "YouTube Analytics API request failed")
        except YouTubeAPIError as e:
            logger.error(f"上位動画リスト取得エラー: {e}")
            return []

        if "rows" not in response:
            return []

        video_ids = [row[0] for row in response["rows"]]
        video_details = self._get_video_details(video_ids)

        results = []
        for i, video_id in enumerate(video_ids, 1):
            logger.info(f"[{i}/{len(video_ids)}] 維持率取得中: {video_id}")
            retention = self.get_audience_retention(video_id, start_date, end_date)
            detail = video_details.get(video_id, {})
            retention["title"] = detail.get("title", "Unknown")
            results.append(retention)

        # 平均維持率で降順ソート
        results.sort(key=lambda x: x.get("average_retention", 0), reverse=True)
        logger.info(f"視聴維持率サマリー完了: {len(results)} 本")
        return results
