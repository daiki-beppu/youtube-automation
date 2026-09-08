"""
視聴維持率の分析関数。APIクライアントと動画詳細取得を明示的に受け取る。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Dict, List

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.analytics.ports import AnalyticsClient
from youtube_automation.domains.analytics.query_contract import (
    TARGETED_QUERY_VIEWS_METRIC,
    TARGETED_QUERY_VIEWS_SORT,
)

logger = logging.getLogger(__name__)


def collect_audience_retention(
    analytics_client: AnalyticsClient, channel_id: str | None, video_id: str, start_date: str, end_date: str
) -> Dict:
    """
    特定動画の視聴維持率曲線を取得

    Args:
        video_id (str): 動画ID
        start_date (str): 開始日
        end_date (str): 終了日

    Returns:
        Dict: 視聴維持率データ（曲線 + サマリー）
    """
    try:
        request = analytics_client.query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="audienceWatchRatio,relativeRetentionPerformance",
            dimensions="elapsedVideoTimeRatio",
            filters=f"video=={video_id}",
            sort="elapsedVideoTimeRatio",
        )
        response = request

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


def collect_retention_summary(
    analytics_client: AnalyticsClient,
    channel_id: str | None,
    start_date: str,
    end_date: str,
    top_n: int,
    *,
    get_video_details: Callable[[list[str]], dict],
    get_retention: Callable[[str, str, str], dict],
) -> List[Dict]:
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
    logger.info(f"視聴維持率サマリー取得: 上位 {top_n} 本")

    # 上位動画の video_id を取得
    try:
        request = analytics_client.query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics=TARGETED_QUERY_VIEWS_METRIC,
            dimensions="video",
            sort=TARGETED_QUERY_VIEWS_SORT,
            maxResults=top_n,
        )
        response = request
    except YouTubeAPIError as e:
        logger.error(f"上位動画リスト取得エラー: {e}")
        raise

    if "rows" not in response:
        return []

    video_ids = [row[0] for row in response["rows"]]
    video_details = get_video_details(video_ids)

    results = []
    for i, video_id in enumerate(video_ids, 1):
        logger.info(f"[{i}/{len(video_ids)}] 維持率取得中: {video_id}")
        retention = get_retention(video_id, start_date, end_date)
        detail = video_details.get(video_id, {})
        retention["title"] = detail.get("title", "Unknown")
        results.append(retention)

    # 平均維持率で降順ソート
    results.sort(key=lambda x: x.get("average_retention", 0), reverse=True)
    logger.info(f"視聴維持率サマリー完了: {len(results)} 本")
    return results
