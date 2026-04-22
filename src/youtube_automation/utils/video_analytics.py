"""
動画別分析 Mixin（コア）
YouTubeAnalyticsCollector の動画レベル分析メソッド群
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List

from googleapiclient.errors import HttpError

if TYPE_CHECKING:
    from .analytics_base import AnalyticsBase  # noqa: F401


logger = logging.getLogger(__name__)


class VideoAnalyticsMixin:
    """動画別の統計データ取得・処理（コアメソッド）"""

    def get_video_analytics(self, start_date: str, end_date: str) -> List[Dict]:
        """
        動画別アナリティクス取得

        Args:
            start_date (str): 開始日
            end_date (str): 終了日

        Returns:
            List[Dict]: 動画別統計データ
        """
        if not self.analytics_service:
            self.initialize()

        logger.info("動画別分析データ取得中: 全動画")

        try:
            # 動画別メトリクス取得
            response = (
                self.analytics_service.reports()
                .query(
                    ids=f"channel=={self.channel_id}",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views,estimatedMinutesWatched,averageViewDuration,likes,dislikes,comments,shares,subscribersGained",
                    dimensions="video",
                    sort="-views",
                    maxResults=10,
                )
                .execute()
            )

            videos_data = []

            if "rows" in response:
                # 動画詳細情報を取得
                video_ids = [row[0] for row in response["rows"]]
                video_details = self._get_video_details(video_ids)

                for i, row in enumerate(response["rows"]):
                    video_id = row[0]
                    video_detail = video_details.get(video_id, {})

                    videos_data.append(
                        {
                            "video_id": video_id,
                            "title": video_detail.get("title", "Unknown"),
                            "published_at": video_detail.get("published_at"),
                            "collection_type": self._classify_video_type(video_detail.get("title", "")),
                            "views": row[1],
                            "watch_time_minutes": row[2],
                            "average_view_duration": row[3],
                            "likes": row[4],
                            "dislikes": row[5],
                            "comments": row[6],
                            "shares": row[7],
                            "subscribers_gained": row[8],
                            "engagement_rate": self._calculate_engagement_rate(row),
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                        }
                    )

            return videos_data

        except HttpError as e:
            logger.error(f"YouTube API エラー（動画別分析）: {e}")
            return []
        except Exception as e:
            logger.error(f"動画別分析取得エラー: {e}")
            return []

    def get_video_analytics_by_id(self, video_id: str, start_date: str, end_date: str) -> Dict:
        """
        特定動画のAnalyticsデータを取得

        Args:
            video_id (str): 動画ID
            start_date (str): 開始日
            end_date (str): 終了日

        Returns:
            Dict: 動画のアナリティクスデータ
        """
        if not self.analytics_service:
            self.initialize()

        try:
            # 動画別メトリクス取得
            response = (
                self.analytics_service.reports()
                .query(
                    ids=f"channel=={self.channel_id}",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views,estimatedMinutesWatched,averageViewDuration,likes,dislikes,comments,shares,subscribersGained",
                    filters=f"video=={video_id}",
                )
                .execute()
            )

            if "rows" in response and response["rows"]:
                row = response["rows"][0]
                return {
                    "video_id": video_id,
                    "views": row[0] if len(row) > 0 else 0,
                    "estimated_minutes_watched": row[1] if len(row) > 1 else 0,
                    "average_view_duration": row[2] if len(row) > 2 else 0,
                    "likes": row[3] if len(row) > 3 else 0,
                    "dislikes": row[4] if len(row) > 4 else 0,
                    "comments": row[5] if len(row) > 5 else 0,
                    "shares": row[6] if len(row) > 6 else 0,
                    "subscribers_gained": row[7] if len(row) > 7 else 0,
                }
            else:
                return {
                    "video_id": video_id,
                    "views": 0,
                    "estimated_minutes_watched": 0,
                    "average_view_duration": 0,
                    "likes": 0,
                    "dislikes": 0,
                    "comments": 0,
                    "shares": 0,
                    "subscribers_gained": 0,
                }

        except HttpError as e:
            logger.error(f"YouTube API エラー（動画ID {video_id}）: {e}")
            return {
                "video_id": video_id,
                "views": 0,
                "estimated_minutes_watched": 0,
                "average_view_duration": 0,
                "likes": 0,
                "dislikes": 0,
                "comments": 0,
                "shares": 0,
                "subscribers_gained": 0,
                "error": str(e),
            }
        except Exception as e:
            logger.error(f"動画ID {video_id} の分析取得エラー: {e}")
            return {
                "video_id": video_id,
                "views": 0,
                "estimated_minutes_watched": 0,
                "average_view_duration": 0,
                "likes": 0,
                "dislikes": 0,
                "comments": 0,
                "shares": 0,
                "subscribers_gained": 0,
                "error": str(e),
            }

    def _get_video_details(self, video_ids: List[str]) -> Dict:
        """動画詳細情報取得"""
        if not video_ids:
            return {}

        try:
            # 50個ずつ分割して処理（API制限対応）
            all_details = {}

            for i in range(0, len(video_ids), 50):
                batch_ids = video_ids[i : i + 50]

                response = (
                    self.youtube_service.videos()
                    .list(part="snippet,statistics,contentDetails,topicDetails", id=",".join(batch_ids))
                    .execute()
                )

                for item in response.get("items", []):
                    video_id = item["id"]
                    snippet = item["snippet"]
                    content_details = item.get("contentDetails", {})
                    topic_details = item.get("topicDetails", {})

                    all_details[video_id] = {
                        "title": snippet["title"],
                        "published_at": snippet["publishedAt"],
                        "description": snippet.get("description", ""),
                        "tags": snippet.get("tags", []),
                        "duration": content_details.get("duration", ""),
                        "definition": content_details.get("definition", ""),
                        "dimension": content_details.get("dimension", ""),
                        "caption": content_details.get("caption", "false"),
                        "topic_categories": topic_details.get("topicCategories", []),
                    }

            return all_details

        except HttpError as e:
            logger.warning(f"YouTube API エラー（動画詳細取得）: {e}")
            return {}
        except Exception as e:
            logger.warning(f"動画詳細取得エラー: {e}")
            return {}

    def _classify_video_type(self, title: str) -> str:
        """動画タイプ分類（Complete Collection vs Individual Track）"""
        title_lower = title.lower()

        if any(keyword in title_lower for keyword in ["tracks", "collection", "full", "complete"]):
            return "Complete Collection"
        else:
            return "Individual Track"

    def _calculate_engagement_rate(self, row: list) -> float:
        """エンゲージメント率計算"""
        try:
            views = row[1]
            likes = row[4]
            comments = row[6]
            shares = row[7]

            if views > 0:
                return ((likes + comments + shares) / views) * 100
            else:
                return 0.0
        except Exception:
            return 0.0
