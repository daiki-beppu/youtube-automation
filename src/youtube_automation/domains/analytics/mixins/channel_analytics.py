"""
チャンネル全体統計 Mixin
YouTubeAnalyticsCollector のチャンネルレベル分析メソッド群
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Dict

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.analytics.query_contract import TARGETED_QUERY_VIEWS_METRIC

if TYPE_CHECKING:
    from youtube_automation.domains.analytics.ports import AnalyticsBase  # noqa: F401

logger = logging.getLogger(__name__)


def _require_analytics_result(result: dict, context: str) -> dict:
    """Promote a required report's embedded API failure to the collection boundary."""
    if "error" in result:
        raise YouTubeAPIError(f"{context}: {result['error']}")
    return result


def _require_retention_results(retention: list[dict]) -> list[dict]:
    """Require every retention result to succeed before publishing the collected data."""
    retention_errors = [item["error"] for item in retention if "error" in item]
    if retention_errors:
        raise YouTubeAPIError(f"視聴維持率分析収集失敗: {retention_errors[0]}")
    return retention


def _daily_row_metrics(row: list) -> Dict:
    """Read required daily metrics and default only the optional trailing columns."""
    required = (
        "date",
        "views",
        "watch_time",
        "avg_duration",
        "subscribers_gained",
        "subscribers_lost",
        "likes",
        "dislikes",
        "comments",
        "shares",
    )
    optional = ("avg_view_percentage", "card_impressions", "card_clicks", "card_click_rate")
    metrics = {field: row[index] for index, field in enumerate(required)}
    metrics.update(dict.fromkeys(optional, 0))
    metrics.update(zip(optional, row[10:14], strict=False))
    return metrics


class ChannelAnalyticsMixin:
    """チャンネル全体の統計データ取得・処理"""

    def _build_publish_at_map(self) -> dict[str, str]:
        """collections/live/ の upload_tracking.json から video_id → publish_at マップを構築。"""
        publish_map: dict[str, str] = {}
        live_dir = self.channel_root / "collections" / "live"
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
        logger.info(f"チャンネル分析データ取得中: {start_date} - {end_date}")

        try:
            # 基本メトリクス
            request = self.analytics_service.query(
                ids=f"channel=={self.channel_id}",
                startDate=start_date,
                endDate=end_date,
                metrics=f"{TARGETED_QUERY_VIEWS_METRIC},estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost,likes,dislikes,comments,shares,averageViewPercentage,cardImpressions,cardClicks,cardClickRate",
                dimensions="day",
            )
            response = request

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
                subscribed_status = _require_analytics_result(
                    self.get_subscribed_status_analytics(start_date, end_date), "登録ステータス分析取得失敗"
                )
                basic_data["audience"] = {
                    "by_device": self.get_device_analytics(start_date, end_date),
                    "by_subscribed_status": subscribed_status,
                }

            # full: + retention + country
            if depth == "full":
                logger.info("地域別分析収集中...")
                by_country = _require_analytics_result(
                    self.get_country_analytics(start_date, end_date), "地域別分析収集失敗"
                )
                basic_data["audience"]["by_country"] = by_country

                logger.info("視聴維持率分析収集中...")
                basic_data["retention"] = _require_retention_results(
                    self.get_retention_summary(start_date, end_date, top_n=10)
                )

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

        except YouTubeAPIError:
            logger.error("エラーが発生したため処理を終了します")
            raise

    def _process_daily_data(self, response: Dict) -> list:
        """日別データ処理"""
        return [_daily_row_metrics(row) for row in response.get("rows", [])]

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
                metrics = _daily_row_metrics(row)
                summary["total_views"] += metrics["views"]
                summary["total_watch_time"] += metrics["watch_time"]
                summary["net_subscribers"] += metrics["subscribers_gained"] - metrics["subscribers_lost"]
                summary["total_engagement"] += metrics["likes"] + metrics["comments"] + metrics["shares"]
                if metrics["avg_view_percentage"]:
                    view_percentages.append(metrics["avg_view_percentage"])
                summary["total_card_impressions"] += metrics["card_impressions"]
                summary["total_card_clicks"] += metrics["card_clicks"]

            if view_percentages:
                summary["avg_view_percentage"] = sum(view_percentages) / len(view_percentages)

        return summary
