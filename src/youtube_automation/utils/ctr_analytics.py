"""CTR・コレクション分析 Mixin

YouTubeAnalyticsCollector の CTR 特化分析メソッド群。

YouTube Analytics API の `channel_reports` 仕様上、
`videoThumbnailImpressions` / `videoThumbnailImpressionsClickRate` は
`Traffic Source Report` / `Traffic Source Detail Report` / `Device Type Report` /
`Operating System Report` でのみ取得可能で、いずれも
- 必須 dimension（`insightTrafficSourceType` / `deviceType` 等）
- 地理 / video / group filter
を同時に要求する。`dimensions` 無し・`dimensions=video` などでは常に 400 が返る。

本 Mixin では Traffic Source Report
(`dimensions=insightTrafficSourceType` + `filters=country==JP`) を採用する。
Browse / Suggested / Search などサムネ接点別の impressions/CTR が得られ、
Studio リーチタブと同じ水準の「どの導線で伸びているか」が分析可能。
全体サマリーは行を合算して返し、ソース別 breakdown も同梱する。
動画別クエリからは impressions 系メトリクスを除外する (API 仕様準拠)。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List

from googleapiclient.errors import HttpError

if TYPE_CHECKING:
    from .analytics_base import AnalyticsBase  # noqa: F401


logger = logging.getLogger(__name__)


class CTRAnalyticsMixin:
    """CTR分析・コレクション別パフォーマンス分析"""

    def get_ctr_analysis(self, start_date: str, end_date: str) -> Dict:
        """
        CTR詳細分析

        Args:
            start_date (str): 開始日
            end_date (str): 終了日

        Returns:
            Dict: CTR分析結果
        """
        if not self.analytics_service:
            self.initialize()

        logger.info("CTR詳細分析実行中...")

        try:
            # 基本メトリクス
            overall_response = (
                self.analytics_service.reports()
                .query(
                    ids=f"channel=={self.channel_id}",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views,likes,comments,shares,subscribersGained",
                )
                .execute()
            )

            # 動画別データ（トップ30）
            video_ctr_response = self._fetch_video_ctr(start_date, end_date)

            # エンゲージメントデータ
            traffic_response = (
                self.analytics_service.reports()
                .query(
                    ids=f"channel=={self.channel_id}",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views,estimatedMinutesWatched",
                    dimensions="day",
                )
                .execute()
            )

            # Device Type Report 経由で取得するが、チャンネル設定やアクセス権限の都合で
            # 400 が返ることがあるため個別に保護する
            try:
                impressions_response = self._fetch_channel_impressions_summary(start_date, end_date)
                impressions_data = self._process_channel_impressions_summary(impressions_response)
            except HttpError as e:
                logger.warning(f"⚠️ チャンネル impressions サマリー取得失敗（続行）: {e}")
                impressions_data = self._process_channel_impressions_summary({})

            overall_data = self._process_overall_ctr(overall_response)
            video_data = self._process_video_ctr(video_ctr_response)
            daily_data = self._process_traffic_source_ctr(traffic_response)
            perf_analysis = self._analyze_ctr_performance(video_ctr_response)

            return {
                "period": f"{start_date} to {end_date}",
                "impressions_summary": impressions_data,
                "overall_engagement": overall_data,
                "video_performance": video_data,
                "daily_traffic": daily_data,
                "performance_analysis": perf_analysis,
                # 後方互換キー
                "overall_ctr": overall_data,
                "video_ctr_ranking": video_data,
                "traffic_source_ctr": daily_data,
                "ctr_analysis": perf_analysis,
            }

        except HttpError as e:
            logger.error(f"YouTube API エラー（CTR分析）: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"CTR分析エラー: {e}")
            return {"error": str(e)}

    def _fetch_video_ctr(self, start_date: str, end_date: str) -> Dict:
        """動画別パフォーマンスデータを取得する（トップ30本、views 降順）"""
        return (
            self.analytics_service.reports()
            .query(
                ids=f"channel=={self.channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="views,likes,comments,estimatedMinutesWatched",
                dimensions="video",
                sort="-views",
                maxResults=30,
            )
            .execute()
        )

    def _fetch_channel_impressions_summary(self, start_date: str, end_date: str) -> Dict:
        """チャンネル全体の impressions/CTR を Traffic Source Report で取得する。

        `videoThumbnailImpressions*` は `dimensions=insightTrafficSourceType` + 必須 filter
        （地理 / video / group）と組み合わせる必要がある。地理 filter は `country==JP` 固定
        （日本語チャンネル前提）。
        row: [insightTrafficSourceType, views, videoThumbnailImpressions, videoThumbnailImpressionsClickRate]
        """
        return (
            self.analytics_service.reports()
            .query(
                ids=f"channel=={self.channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="views,videoThumbnailImpressions,videoThumbnailImpressionsClickRate",
                dimensions="insightTrafficSourceType",
                filters="country==JP",
            )
            .execute()
        )

    def _process_channel_impressions_summary(self, response: Dict) -> Dict:
        """Traffic Source Report を合算してサマリー + ソース別 breakdown を返す。

        row: [insightTrafficSourceType, views, impressions, impression_ctr]
        - 全体 CTR は `sum(views_from_impressions) / sum(impressions)` で再計算。
        - breakdown は impressions が発生したソースのみ impressions 降順で返す
          (External / Direct などは impressions=0 の行が返るため除外)。
        """
        empty = {
            "total_impressions": 0,
            "total_views_from_impressions": 0,
            "aggregated_ctr_percentage": 0,
            "traffic_source_breakdown": [],
        }

        rows = response.get("rows") or []
        if not rows:
            return empty

        total_views = 0
        total_impressions = 0
        breakdown: List[Dict] = []
        for row in rows:
            source = row[0] if len(row) > 0 else "UNKNOWN"
            views = row[1] if len(row) > 1 else 0
            impressions = row[2] if len(row) > 2 else 0
            ctr = row[3] if len(row) > 3 else 0
            if impressions <= 0:
                # External / Direct などサムネ接点のない流入は impressions=0 なので
                # views_from_impressions からも除外する (セマンティクス的に整合)
                continue
            total_views += views
            total_impressions += impressions
            breakdown.append(
                {
                    "traffic_source": source,
                    "views_from_impressions": views,
                    "impressions": impressions,
                    "impression_ctr_percentage": round(ctr, 2),
                }
            )

        breakdown.sort(key=lambda r: r["impressions"], reverse=True)
        aggregated_ctr = (total_views / total_impressions * 100) if total_impressions > 0 else 0

        return {
            "total_impressions": total_impressions,
            "total_views_from_impressions": total_views,
            "aggregated_ctr_percentage": round(aggregated_ctr, 2),
            "traffic_source_breakdown": breakdown,
        }

    def get_collection_performance(self, start_date: str, end_date: str) -> Dict:
        """
        コレクション別パフォーマンス分析

        Args:
            start_date (str): 開始日
            end_date (str): 終了日

        Returns:
            Dict: コレクション分析結果
        """
        logger.info("コレクション別パフォーマンス分析中...")

        # 動画データ取得
        videos_data = self.get_video_analytics(start_date, end_date)

        if not videos_data:
            return {"error": "データが取得できませんでした"}

        # コレクション分類
        collections = {
            "Adventure": [],
            "Battle": [],
            "Boss Battle": [],
            "Village/Town": [],
            "Dungeon": [],
            "Castle": [],
            "Field": [],
            "Ocean": [],
            "Other": [],
        }

        for video in videos_data:
            collection_type = self._classify_collection_type(video["title"])
            collections[collection_type].append(video)

        # コレクション別統計計算
        collection_stats = {}
        for collection_name, videos in collections.items():
            if videos:
                collection_stats[collection_name] = self._calculate_collection_stats(videos)

        return {
            "period": f"{start_date} to {end_date}",
            "collection_performance": collection_stats,
            "top_performers": self._identify_top_performers(videos_data),
            "ctr_by_collection": self._analyze_ctr_by_collection(videos_data),
            "recommendations": self._generate_collection_recommendations(collection_stats),
        }

    def _classify_collection_type(self, title: str) -> str:
        """コレクションタイプ分類"""
        title_lower = title.lower()

        classification_map = {
            "adventure": "Adventure",
            "boss": "Boss Battle",
            "battle": "Battle",
            "village": "Village/Town",
            "town": "Village/Town",
            "dungeon": "Dungeon",
            "castle": "Castle",
            "field": "Field",
            "ocean": "Ocean",
        }

        for keyword, collection_type in classification_map.items():
            if keyword in title_lower:
                return collection_type

        return "Other"

    def _process_overall_ctr(self, response: Dict) -> Dict:
        """全体エンゲージメント処理

        views / likes / comments / shares / subscribersGained を返す。
        サムネ impressions/CTR は `_process_channel_impressions_summary` 側で扱う。
        """
        if "rows" in response and response["rows"]:
            row = response["rows"][0]
            return {
                "total_views": row[0],
                "total_likes": row[1],
                "total_comments": row[2],
                "total_shares": row[3],
                "subscribers_gained": row[4],
            }
        return {}

    def _evaluate_ctr_performance(self, ctr: float) -> str:
        """CTRパフォーマンス評価"""
        if ctr >= 2.0:
            return "Excellent (目標達成)"
        elif ctr >= 1.5:
            return "Good (改善中)"
        elif ctr >= 1.0:
            return "Average (要改善)"
        else:
            return "Poor (緊急改善必要)"

    def _process_video_ctr(self, response: Dict) -> List[Dict]:
        """動画別パフォーマンス処理

        row: [video_id, views, likes, comments, watch_time]
        """
        if "rows" not in response:
            return []

        video_ids = [row[0] for row in response["rows"]]
        video_details = self._get_video_details(video_ids)

        video_data = []
        for row in response["rows"]:
            video_id = row[0]
            video_detail = video_details.get(video_id, {})
            video_data.append(
                {
                    "video_id": video_id,
                    "title": video_detail.get("title", "Unknown"),
                    "views": row[1],
                    "likes": row[2],
                    "comments": row[3],
                    "watch_time_minutes": row[4],
                    "collection_type": self._classify_collection_type(video_detail.get("title", "")),
                }
            )

        return video_data

    def _process_traffic_source_ctr(self, response: Dict) -> List[Dict]:
        """日別トラフィック処理
        メトリクス: views,estimatedMinutesWatched (dimensions=day)
        row: [date, views, watch_time_minutes]
        """
        daily_traffic = []

        if "rows" in response:
            for row in response["rows"]:
                daily_traffic.append(
                    {
                        "date": row[0],
                        "views": row[1],
                        "watch_time_minutes": row[2],
                    }
                )

        return daily_traffic

    def _analyze_ctr_performance(self, response: Dict) -> Dict:
        """動画パフォーマンス分析（views サマリ）

        動画別クエリでは impressions/CTR が取得できないため、views 統計のみを返す。
        チャンネル全体の impressions/CTR サマリーは `impressions_summary` 側に格納される。
        """
        if not response.get("rows"):
            return {}

        views = [row[1] for row in response["rows"]]

        return {
            "highest_views": max(views),
            "lowest_views": min(views),
            "average_views": sum(views) / len(views),
            "total_videos": len(views),
        }

    def _calculate_collection_stats(self, videos: List[Dict]) -> Dict:
        """コレクション統計計算"""
        if not videos:
            return {}

        total_views = sum(v["views"] for v in videos)
        total_engagement = sum(v.get("likes", 0) + v.get("comments", 0) + v.get("shares", 0) for v in videos)
        total_impressions = sum(v.get("impressions", 0) for v in videos)

        stats = {
            "video_count": len(videos),
            "total_views": total_views,
            "average_views": total_views / len(videos),
            "total_watch_time": sum(v.get("watch_time_minutes", 0) for v in videos),
            "total_engagement": total_engagement,
            "average_engagement_rate": sum(v.get("engagement_rate", 0) for v in videos) / len(videos),
            "subscribers_gained": sum(v.get("subscribers_gained", 0) for v in videos),
        }

        if total_impressions > 0:
            stats["total_impressions"] = total_impressions
            stats["average_ctr"] = (total_views / total_impressions) * 100

        return stats

    def _identify_top_performers(self, videos: List[Dict]) -> Dict:
        """トップパフォーマー特定"""
        if not videos:
            return {}

        # 各メトリクスでのトップ3
        top_by_views = sorted(videos, key=lambda x: x["views"], reverse=True)[:3]
        top_by_engagement = sorted(videos, key=lambda x: x["engagement_rate"], reverse=True)[:3]

        return {
            "top_by_views": [{"title": v["title"], "views": v["views"], "url": v["url"]} for v in top_by_views],
            "top_by_engagement": [
                {"title": v["title"], "rate": v["engagement_rate"], "url": v["url"]} for v in top_by_engagement
            ],
        }

    def _analyze_ctr_by_collection(self, videos: List[Dict]) -> Dict:
        """コレクション別CTR分析（推定）"""
        collection_performance = {}

        for video in videos:
            collection = video["collection_type"]
            if collection not in collection_performance:
                collection_performance[collection] = []
            collection_performance[collection].append(video)

        return {
            collection: self._calculate_collection_stats(vids) for collection, vids in collection_performance.items()
        }

    def _generate_collection_recommendations(self, collection_stats: Dict) -> List[str]:
        """改善提案生成"""
        recommendations = []

        if not collection_stats:
            return ["データが不足しています"]

        # パフォーマンス分析と提案
        best_performer = max(collection_stats.items(), key=lambda x: x[1].get("average_views", 0))

        recommendations.append(f"🏆 最高パフォーマンス: {best_performer[0]} コレクション")
        recommendations.append(f"💡 {best_performer[0]} の成功要因を他のコレクションに適用を検討")

        # CTR改善提案
        recommendations.append("🎯 CTR改善策:")
        recommendations.append("  - Boss Battle系のサムネイル技法を他テーマに応用")
        recommendations.append("  - Adventure系の感情訴求強化")
        recommendations.append("  - モバイル最適化の徹底")

        return recommendations
