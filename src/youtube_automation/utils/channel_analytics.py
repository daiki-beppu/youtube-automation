"""
チャンネル全体統計 Mixin
YouTubeAnalyticsCollector のチャンネルレベル分析メソッド群
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Dict

from youtube_automation.configuration import channel_dir
from youtube_automation.infrastructure.errors import YouTubeAPIError
from youtube_automation.infrastructure.retry import execute_with_retry

if TYPE_CHECKING:
    from .analytics_base import AnalyticsBase  # noqa: F401

logger = logging.getLogger(__name__)


class ChannelAnalyticsMixin:
    """チャンネル全体の統計データ取得・処理"""

    def _build_publish_at_map(self) -> dict[str, str]:
        """collections/live/ の upload_tracking.json から video_id → publish_at マップを構築。"""
        publish_map: dict[str, str] = {}
        live_dir = channel_dir() / "collections" / "live"
        if not live_dir.exists():
            return publish_map
        for collection_dir in live_dir.iterdir():
            if not collection_dir.is_dir():
                continue
            tracking = collection_dir / "20-documentation" / "upload_tracking.json"
            if not tracking.exists():
                continue
            try:
                data = json.loads(tracking.read_text())
                cc = data.get("complete_collection", {})
                vid = cc.get("video_id")
                pub = cc.get("publish_at")
                if vid and pub:
                    publish_map[vid] = pub
            except (json.JSONDecodeError, OSError):
                continue
        return publish_map

    def get_channel_analytics(self, start_date: str, end_date: str) -> Dict:
        """
        チャンネル全体のアナリティクス取得

        Args:
            start_date (str): 開始日 (YYYY-MM-DD)
            end_date (str): 終了日 (YYYY-MM-DD)

        Returns:
            Dict: チャンネル統計データ
        """
        if not self.analytics_service:
            self.initialize()

        logger.info(f"チャンネル分析データ取得中: {start_date} - {end_date}")

        try:
            # 基本メトリクス
            request = self.analytics_service.reports().query(
                ids=f"channel=={self.channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost,likes,dislikes,comments,shares,averageViewPercentage,cardImpressions,cardClicks,cardClickRate",
                dimensions="day",
            )
            response = execute_with_retry(request, "YouTube Analytics API request failed")

            # Note: サムネイル CTR (impressions/impressionClickThroughRate) は
            # チャンネルレベル (dimensions=day) では取得不可。
            # 動画レベル (dimensions=video) では CTRAnalyticsMixin で取得を試行する。

            return {
                "period": f"{start_date} to {end_date}",
                "daily_metrics": self._process_daily_data(response),
                "ctr_data": {
                    "impressions": 0,
                    "ctr_percentage": 0,
                    "note": "Channel-level CTR requires video-level aggregation",
                },
                "summary": self._calculate_summary_stats(response),
            }

        except YouTubeAPIError as e:
            logger.error(f"YouTube API エラー（チャンネル分析）: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"チャンネル分析取得エラー: {e}")
            return {"error": str(e)}

    def collect_basic_analytics(self, start_date: str, end_date: str, depth: str = "standard") -> Dict:
        """
        アナリティクスデータ収集

        Args:
            start_date (str): 開始日 (YYYY-MM-DD)
            end_date (str): 終了日 (YYYY-MM-DD)
            depth (str): 収集深度
                - "basic": 既存メトリクスのみ（クォータ節約、後方互換）
                - "standard": + impressions/CTR + traffic source + playlist + device + audience（推奨）
                - "full": + retention + country（全メトリクス）

        Returns:
            Dict: 収集されたアナリティクスデータ
        """
        logger.info(f"アナリティクス収集: {start_date} 〜 {end_date} (depth={depth})")

        try:
            # サービス初期化
            self.initialize()

            # 基本データ収集
            logger.info("チャンネル統計データ収集中...")
            channel_analytics = self.get_channel_analytics(start_date, end_date)

            logger.info("動画別パフォーマンス収集中...")
            strategic_analytics = self.get_strategic_video_analytics(start_date, end_date, mode="efficient")

            # 戦略的分析結果から動画データを統合
            video_analytics = strategic_analytics["top_videos"] + strategic_analytics["recent_videos"]

            # 動画データをキー化
            video_data = {}
            for video in video_analytics:
                video_id = video.get("video_id")
                if video_id:
                    video_data[video_id] = video

            # upload_tracking から予約公開日時を注入
            publish_at_map = self._build_publish_at_map()
            for vid, entry in video_data.items():
                entry["scheduled_publish_at"] = publish_at_map.get(vid)

            logger.info("公開予約動画数を収集中...")
            scheduled_video_count = self.get_scheduled_video_count()

            # 基本データ構築
            logger.info("収益メトリクス収集中...")
            revenue_analytics = self.get_revenue_analytics(start_date, end_date)
            for video_id, revenue in revenue_analytics["by_video"].items():
                if video_id in video_data:
                    video_data[video_id].update(revenue)

            basic_data = {
                "collection_period": {
                    "start_date": start_date,
                    "end_date": end_date,
                    "collected_at": datetime.now().isoformat(),
                },
                "collection_depth": depth,
                "channel_analytics": channel_analytics,
                "video_analytics": video_data,
                "scheduled_videos": {"count": scheduled_video_count},
                "revenue_analytics": revenue_analytics,
                "strategic_analysis": strategic_analytics,
            }

            # standard 以上: impressions/CTR + traffic source + playlist + device + audience
            if depth in ("standard", "full"):
                logger.info("CTR 詳細分析収集中...")
                basic_data["ctr_analysis"] = self.get_ctr_analysis(start_date, end_date)

                logger.info("トラフィックソース分析収集中...")
                basic_data["traffic_sources"] = self.get_traffic_source_analytics(start_date, end_date)

                logger.info("YT_SEARCH 検索語詳細収集中...")
                basic_data["traffic_sources"]["search_terms"] = self.get_traffic_source_detail(
                    start_date, end_date, "YT_SEARCH"
                )

                logger.info("プレイリスト別分析収集中...")
                basic_data["playlist_analytics"] = self.get_playlist_analytics(start_date, end_date)

                logger.info("オーディエンス分析収集中...")
                subscribed_status = self.get_subscribed_status_analytics(start_date, end_date)
                if "error" in subscribed_status:
                    raise YouTubeAPIError(f"登録ステータス分析取得失敗: {subscribed_status['error']}")
                basic_data["audience"] = {
                    "by_device": self.get_device_analytics(start_date, end_date),
                    "by_subscribed_status": subscribed_status,
                }

            # full: + retention + country
            if depth == "full":
                logger.info("地域別分析収集中...")
                by_country = self.get_country_analytics(start_date, end_date)
                if "error" in by_country:
                    raise YouTubeAPIError(f"地域別分析収集失敗: {by_country['error']}")
                basic_data["audience"]["by_country"] = by_country

                logger.info("視聴維持率分析収集中...")
                retention = self.get_retention_summary(start_date, end_date, top_n=10)
                retention_errors = [item["error"] for item in retention if "error" in item]
                if retention_errors:
                    raise YouTubeAPIError(f"視聴維持率分析収集失敗: {retention_errors[0]}")
                basic_data["retention"] = retention

            # サマリー
            basic_data["summary"] = {
                "total_videos_analyzed": len(video_data),
                "strategic_mode": strategic_analytics["mode"],
                "analysis_breakdown": strategic_analytics["summary"],
                "date_range_days": (
                    datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")
                ).days,
                "collection_version": "3.0",
                "depth": depth,
            }

            logger.info(f"アナリティクス収集完了 (depth={depth})")
            return basic_data

        except Exception as e:
            logger.error(f"データ収集エラー: {e}")
            logger.error("エラーが発生したため処理を終了します")
            raise

    def _process_daily_data(self, response: Dict) -> list:
        """日別データ処理"""
        daily_data = []

        if "rows" in response:
            for row in response["rows"]:
                daily_data.append(
                    {
                        "date": row[0],
                        "views": row[1],
                        "watch_time": row[2],
                        "avg_duration": row[3],
                        "subscribers_gained": row[4],
                        "subscribers_lost": row[5],
                        "likes": row[6],
                        "dislikes": row[7],
                        "comments": row[8],
                        "shares": row[9],
                        "avg_view_percentage": row[10] if len(row) > 10 else 0,
                        "card_impressions": row[11] if len(row) > 11 else 0,
                        "card_clicks": row[12] if len(row) > 12 else 0,
                        "card_click_rate": row[13] if len(row) > 13 else 0,
                    }
                )

        return daily_data

    def _calculate_summary_stats(self, main_response: Dict) -> Dict:
        """サマリー統計計算"""
        summary = {
            "total_views": 0,
            "total_watch_time": 0,
            "net_subscribers": 0,
            "total_engagement": 0,
            "avg_view_percentage": 0,
            "total_card_impressions": 0,
            "total_card_clicks": 0,
        }

        if "rows" in main_response:
            view_percentages = []
            for row in main_response["rows"]:
                summary["total_views"] += row[1]
                summary["total_watch_time"] += row[2]
                summary["net_subscribers"] += row[4] - row[5]
                summary["total_engagement"] += row[6] + row[8] + row[9]
                if len(row) > 10 and row[10]:
                    view_percentages.append(row[10])
                if len(row) > 11:
                    summary["total_card_impressions"] += row[11]
                if len(row) > 12:
                    summary["total_card_clicks"] += row[12]

            if view_percentages:
                summary["avg_view_percentage"] = sum(view_percentages) / len(view_percentages)

        return summary
