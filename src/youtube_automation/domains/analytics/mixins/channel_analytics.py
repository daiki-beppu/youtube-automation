"""
チャンネル全体統計 Mixin
YouTubeAnalyticsCollector のチャンネルレベル分析メソッド群
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Dict

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.domains.analytics.query_contract import TARGETED_QUERY_VIEWS_METRIC

if TYPE_CHECKING:
    from youtube_automation.domains.analytics.ports import AnalyticsBase  # noqa: F401

logger = logging.getLogger(__name__)


def _collect_report(
    collection_errors: dict[str, str],
    label: str,
    collect: Callable[[], object],
    fallback: object = None,
) -> object:
    """Run one report query; record its failure in ``collection_errors`` and keep collecting."""
    try:
        result = collect()
    except YouTubeAPIError as error:
        logger.warning("%s に失敗したため、この項目をスキップして収集を継続します: %s", label, error)
        collection_errors[label] = str(error)
        return fallback
    if isinstance(result, dict) and result.get("error"):
        collection_errors[label] = str(result["error"])
    elif isinstance(result, list):
        item_errors = [str(item["error"]) for item in result if isinstance(item, dict) and item.get("error")]
        if item_errors:
            collection_errors[label] = item_errors[0]
    return result


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

            collection_errors: dict[str, str] = {}

            # 基本データ収集
            logger.info("チャンネル統計データ収集中...")
            channel_analytics = _collect_report(
                collection_errors,
                "チャンネル統計",
                lambda: self.get_channel_analytics(start_date, end_date),
                {},
            )

            logger.info("動画別パフォーマンス収集中...")
            strategic_analytics = _collect_report(
                collection_errors,
                "動画別パフォーマンス",
                lambda: self.get_strategic_video_analytics(start_date, end_date, mode="efficient"),
                {"mode": "efficient", "top_videos": [], "recent_videos": [], "summary": {}},
            )

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
            scheduled_video_count = _collect_report(collection_errors, "公開予約動画数", self.get_scheduled_video_count)

            # 基本データ構築
            logger.info("収益メトリクス収集中...")
            revenue_analytics = _collect_report(
                collection_errors,
                "収益メトリクス",
                lambda: self.get_revenue_analytics(start_date, end_date),
                {"status": "unavailable", "daily_metrics": [], "by_video": {}, "summary": {}},
            )
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
                basic_data["ctr_analysis"] = _collect_report(
                    collection_errors,
                    "CTR詳細分析",
                    lambda: self.get_ctr_analysis(start_date, end_date),
                    {},
                )

                logger.info("トラフィックソース分析収集中...")
                basic_data["traffic_sources"] = _collect_report(
                    collection_errors,
                    "トラフィックソース分析",
                    lambda: self.get_traffic_source_analytics(start_date, end_date),
                    {},
                )

                logger.info("YT_SEARCH 検索語詳細収集中...")
                basic_data["traffic_sources"]["search_terms"] = _collect_report(
                    collection_errors,
                    "検索語詳細",
                    lambda: self.get_traffic_source_detail(start_date, end_date, "YT_SEARCH"),
                    [],
                )

                logger.info("プレイリスト別分析収集中...")
                basic_data["playlist_analytics"] = _collect_report(
                    collection_errors,
                    "プレイリスト別分析",
                    lambda: self.get_playlist_analytics(start_date, end_date),
                    {},
                )

                logger.info("オーディエンス分析収集中...")
                basic_data["audience"] = {
                    "by_device": _collect_report(
                        collection_errors,
                        "デバイス別分析",
                        lambda: self.get_device_analytics(start_date, end_date),
                        {},
                    ),
                    "by_subscribed_status": _collect_report(
                        collection_errors,
                        "登録ステータス分析",
                        lambda: self.get_subscribed_status_analytics(start_date, end_date),
                        {},
                    ),
                }

            # full: + retention + country
            if depth == "full":
                logger.info("地域別分析収集中...")
                basic_data["audience"]["by_country"] = _collect_report(
                    collection_errors,
                    "地域別分析",
                    lambda: self.get_country_analytics(start_date, end_date),
                    {},
                )

                logger.info("視聴維持率分析収集中...")
                basic_data["retention"] = _collect_report(
                    collection_errors,
                    "視聴維持率分析",
                    lambda: self.get_retention_summary(start_date, end_date, top_n=10),
                    [],
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

            if collection_errors:
                basic_data["collection_errors"] = collection_errors
                logger.warning(
                    "一部の収集項目が失敗しました（取得済み分は保存します）: %s",
                    ", ".join(collection_errors),
                )

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
