"""
戦略的分析 Mixin
YouTubeAnalyticsCollector の統合・戦略的動画分析メソッド群
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict, List

from youtube_automation.utils.exceptions import YouTubeAPIError
from youtube_automation.utils.profile import section
from youtube_automation.utils.retry import execute_with_retry

if TYPE_CHECKING:
    from .analytics_base import AnalyticsBase  # noqa: F401


logger = logging.getLogger(__name__)

# YouTube Analytics API は 720 req/min クォータ。w=8 で 50ms レイテンシ時の理論上限 160 req/s
# はクォータ側がボトルネックになるため安全。指示書 #311 の計測で w=8 → 7.7x speedup。
_MAX_WORKERS = 8


class StrategicAnalyticsMixin:
    """戦略的分析の Mixin"""

    @staticmethod
    def _add_subscriber_conversion_rates(videos: List[Dict]) -> None:
        """各動画に再生あたりの登録転換率（%）を付与する。"""
        for video in videos:
            views = video.get("views", 0)
            subscribers_gained = video.get("subscribers_gained", 0)
            video["subscriber_conversion_rate"] = round((subscribers_gained / views) * 100, 2) if views > 0 else 0

    @staticmethod
    def _build_subscriber_conversion_ranking(videos: List[Dict]) -> List[Dict]:
        """登録転換率順の動画ランキングを、レポート用の必要項目だけで構築する。"""
        ranking = [
            {
                "video_id": video.get("video_id"),
                "title": video.get("title", "Unknown"),
                "duration": video.get("duration", ""),
                "views": video.get("views", 0),
                "subscribers_gained": video.get("subscribers_gained", 0),
                "subscriber_conversion_rate": video.get("subscriber_conversion_rate", 0),
            }
            for video in videos
        ]
        return sorted(ranking, key=lambda video: video["subscriber_conversion_rate"], reverse=True)

    def get_combined_analytics(
        self, start_date: str, end_date: str, top_count: int = 50, recent_days: int = 30
    ) -> Dict:
        """
        上位動画と直近投稿動画の統合取得（重複排除・一回取得）

        Args:
            start_date (str): 分析開始日
            end_date (str): 分析終了日
            top_count (int): 上位動画数（デフォルト50本）
            recent_days (int): 直近日数（デフォルト30日）

        Returns:
            Dict: 統合分析データ
        """
        logger.info(f"統合Analytics取得: 上位{top_count}本 + 直近{recent_days}日投稿")

        # Step 1: 全動画リストを一回で取得
        logger.info("全動画リスト取得中...")
        all_videos = self.get_all_channel_videos()
        if not all_videos:
            return {"top_videos": [], "recent_videos": []}

        # Step 2: 直近投稿動画をフィルタリング
        logger.info(f"直近{recent_days}日間の投稿動画をフィルタリング中...")
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=recent_days)

        recent_video_ids = set()
        recent_videos_info = []

        for video in all_videos:
            published_date = datetime.fromisoformat(video["published_at"].replace("Z", "+00:00"))
            if published_date >= cutoff_date:
                recent_video_ids.add(video["video_id"])
                recent_videos_info.append(video)

        logger.info(f"直近投稿動画: {len(recent_videos_info)}本")

        # Step 3: 上位動画を効率的に取得
        logger.info(f"上位{top_count}本の動画Analytics取得中...")
        top_videos_data = []
        remaining_count = top_count

        while remaining_count > 0 and len(top_videos_data) < top_count:
            batch_size = min(10, remaining_count)

            try:
                request = self.analytics_service.reports().query(
                    ids=f"channel=={self.channel_id}",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views,estimatedMinutesWatched,averageViewDuration,likes,dislikes,comments,shares,subscribersGained",
                    dimensions="video",
                    sort="-views",
                    maxResults=batch_size,
                    startIndex=len(top_videos_data) + 1,
                )
                response = execute_with_retry(request, "YouTube Analytics API request failed")

                if "rows" not in response:
                    break

                # 動画詳細を取得
                video_ids = [row[0] for row in response["rows"]]
                video_details = self._get_video_details(video_ids)

                for row in response["rows"]:
                    video_id = row[0]
                    video_detail = video_details.get(video_id, {})

                    video_data = {
                        "video_id": video_id,
                        "title": video_detail.get("title", "Unknown"),
                        "published_at": video_detail.get("published_at"),
                        "description": (
                            video_detail.get("description", "")[:100] + "..."
                            if len(video_detail.get("description", "")) > 100
                            else video_detail.get("description", "")
                        ),
                        "duration": video_detail.get("duration", ""),
                        "definition": video_detail.get("definition", ""),
                        "views": row[1],
                        "estimated_minutes_watched": row[2],
                        "average_view_duration": row[3],
                        "likes": row[4] if len(row) > 4 else 0,
                        "dislikes": row[5] if len(row) > 5 else 0,
                        "comments": row[6] if len(row) > 6 else 0,
                        "shares": row[7] if len(row) > 7 else 0,
                        "subscribers_gained": row[8] if len(row) > 8 else 0,
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "is_recent": video_id in recent_video_ids,
                    }
                    top_videos_data.append(video_data)

                remaining_count -= len(response["rows"])

                if len(response["rows"]) < batch_size:
                    break

            except YouTubeAPIError as e:
                logger.error(f"YouTube API エラー（上位動画取得）: {e}")
                break
            except Exception as e:
                logger.error(f"上位動画取得エラー: {e}")
                break

        # Step 4: 直近動画のAnalytics取得（上位に含まれていないもののみ）
        logger.info("直近投稿動画のAnalytics取得中...")
        top_video_ids = {video["video_id"] for video in top_videos_data}

        recent_videos_data = []
        for video in recent_videos_info:
            if video["video_id"] not in top_video_ids:
                analytics_data = self.get_video_analytics_by_id(video["video_id"], start_date, end_date)

                combined_data = {**video, **analytics_data, "is_recent": True}
                recent_videos_data.append(combined_data)

        # 再生回数で降順ソート
        recent_videos_data.sort(key=lambda x: x.get("views", 0), reverse=True)
        self._add_subscriber_conversion_rates(top_videos_data)
        self._add_subscriber_conversion_rates(recent_videos_data)

        # 結果
        result = {
            "top_videos": top_videos_data,
            "recent_videos": recent_videos_data,
            "statistics": {
                "top_videos_count": len(top_videos_data),
                "recent_videos_count": len(recent_videos_data),
                "recent_in_top": len([v for v in top_videos_data if v.get("is_recent")]),
                "unique_recent_videos": len(recent_videos_data),
                "total_analyzed": len(top_videos_data) + len(recent_videos_data),
            },
        }

        logger.info("統合Analytics取得完了:")
        logger.info(f"上位動画: {len(top_videos_data)}本")
        logger.info(f"直近動画（上位外）: {len(recent_videos_data)}本")
        logger.info(f"直近動画（上位内）: {result['statistics']['recent_in_top']}本")
        logger.info(f"総計: {result['statistics']['total_analyzed']}本")

        return result

    def get_strategic_video_analytics(self, start_date: str, end_date: str, mode: str = "efficient") -> Dict:
        """
        戦略的動画分析データ取得（モード選択可能）

        Args:
            start_date (str): 分析開始日
            end_date (str): 分析終了日
            mode (str): 取得モード
                - "efficient": 上位50本 + 直近30日投稿（推奨）
                - "comprehensive": 全動画
                - "top_only": 上位50本のみ
                - "recent_only": 直近30日投稿のみ

        Returns:
            Dict: 分析データ
        """
        logger.info(f"戦略的動画分析データ取得開始 (モード: {mode})")

        result = {
            "mode": mode,
            "period": f"{start_date} to {end_date}",
            "top_videos": [],
            "recent_videos": [],
            "all_videos": [],
        }

        if mode == "efficient":
            logger.info("効率モード: 上位50本 + 直近30日投稿（統合取得）")
            combined_data = self.get_combined_analytics(start_date, end_date, 50, 30)
            result["top_videos"] = combined_data["top_videos"]
            result["recent_videos"] = combined_data["recent_videos"]

        elif mode == "comprehensive":
            logger.info("包括モード: 全動画")
            result["all_videos"] = self.get_all_video_analytics(start_date, end_date)

        elif mode == "top_only":
            logger.info("上位のみモード: 上位50本")
            result["top_videos"] = self.get_top_video_analytics(start_date, end_date, 50)

        elif mode == "recent_only":
            logger.info("直近のみモード: 直近30日投稿")
            result["recent_videos"] = self.get_recent_video_analytics(start_date, end_date, 30)

        else:
            logger.error(f"不明なモード: {mode}")
            logger.info("利用可能なモード: efficient, comprehensive, top_only, recent_only")
            return result

        # 統計情報を追加
        total_videos = len(result["top_videos"]) + len(result["recent_videos"]) + len(result["all_videos"])
        all_videos = result["top_videos"] + result["recent_videos"] + result["all_videos"]
        self._add_subscriber_conversion_rates(all_videos)
        result["summary"] = {
            "total_videos_analyzed": total_videos,
            "top_videos_count": len(result["top_videos"]),
            "recent_videos_count": len(result["recent_videos"]),
            "all_videos_count": len(result["all_videos"]),
        }
        result["subscriber_conversion_ranking"] = self._build_subscriber_conversion_ranking(all_videos)

        logger.info(f"戦略的分析データ取得完了: 総計{total_videos}本")
        return result

    def get_all_video_analytics(self, start_date: str, end_date: str) -> List[Dict]:
        """
        全動画のアナリティクス取得（制限なし版）

        Args:
            start_date (str): 開始日
            end_date (str): 終了日

        Returns:
            List[Dict]: 全動画の統計データ
        """
        logger.info("動画別分析データ取得中: 全動画（制限なし）")

        # Step 1: 全動画リストを取得
        all_videos = self.get_all_channel_videos()
        if not all_videos:
            logger.error("動画リストの取得に失敗しました")
            return []

        logger.info(f"{len(all_videos)}本の動画のAnalyticsデータを取得開始...")

        # Step 2: 各動画のAnalyticsデータを並列取得
        videos_data = self._fetch_videos_analytics_parallel(
            all_videos, start_date, end_date, "strategic_analytics.all_videos_loop"
        )

        # 再生回数で降順ソート
        videos_data.sort(key=lambda x: x.get("views", 0), reverse=True)
        self._add_subscriber_conversion_rates(videos_data)

        logger.info(f"全動画Analytics取得完了: {len(videos_data)}本")
        return videos_data

    def get_top_video_analytics(self, start_date: str, end_date: str, top_count: int = 50) -> List[Dict]:
        """
        上位N本の動画アナリティクス取得（効率版）

        Args:
            start_date (str): 開始日
            end_date (str): 終了日
            top_count (int): 取得する上位動画数（デフォルト50本）

        Returns:
            List[Dict]: 上位動画の統計データ
        """
        logger.info(f"上位{top_count}本の動画分析データ取得中...")

        videos_data = []
        remaining_count = top_count

        while remaining_count > 0 and len(videos_data) < top_count:
            batch_size = min(10, remaining_count)

            try:
                request = self.analytics_service.reports().query(
                    ids=f"channel=={self.channel_id}",
                    startDate=start_date,
                    endDate=end_date,
                    metrics="views,estimatedMinutesWatched,averageViewDuration,likes,dislikes,comments,shares,subscribersGained",
                    dimensions="video",
                    sort="-views",
                    maxResults=batch_size,
                    startIndex=len(videos_data) + 1,
                )
                response = execute_with_retry(request, "YouTube Analytics API request failed")

                if "rows" not in response:
                    break

                # 動画詳細を取得
                video_ids = [row[0] for row in response["rows"]]
                video_details = self._get_video_details(video_ids)

                for row in response["rows"]:
                    video_id = row[0]
                    video_detail = video_details.get(video_id, {})

                    video_data = {
                        "video_id": video_id,
                        "title": video_detail.get("title", "Unknown"),
                        "published_at": video_detail.get("published_at"),
                        "description": (
                            video_detail.get("description", "")[:100] + "..."
                            if len(video_detail.get("description", "")) > 100
                            else video_detail.get("description", "")
                        ),
                        "duration": video_detail.get("duration", ""),
                        "definition": video_detail.get("definition", ""),
                        "views": row[1],
                        "estimated_minutes_watched": row[2],
                        "average_view_duration": row[3],
                        "likes": row[4] if len(row) > 4 else 0,
                        "dislikes": row[5] if len(row) > 5 else 0,
                        "comments": row[6] if len(row) > 6 else 0,
                        "shares": row[7] if len(row) > 7 else 0,
                        "subscribers_gained": row[8] if len(row) > 8 else 0,
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                    }
                    videos_data.append(video_data)

                remaining_count -= len(response["rows"])
                logger.info(f"{len(videos_data)}本取得済み...")

                # レスポンスが期待より少ない場合は終了
                if len(response["rows"]) < batch_size:
                    break

            except YouTubeAPIError as e:
                logger.error(f"YouTube API エラー（バッチ取得）: {e}")
                break
            except Exception as e:
                logger.error(f"バッチ取得エラー: {e}")
                break

        logger.info(f"上位動画Analytics取得完了: {len(videos_data)}本")
        self._add_subscriber_conversion_rates(videos_data)
        return videos_data

    def get_recent_video_analytics(self, start_date: str, end_date: str, days: int = 30) -> List[Dict]:
        """
        直近N日間投稿動画のアナリティクス取得

        Args:
            start_date (str): 分析開始日
            end_date (str): 分析終了日
            days (int): 投稿から何日以内の動画を対象とするか

        Returns:
            List[Dict]: 直近投稿動画の統計データ
        """
        logger.info(f"直近{days}日間投稿動画の分析データ取得中...")

        # 直近投稿動画を取得
        recent_videos = self.get_recent_videos(days)
        if not recent_videos:
            logger.error("直近投稿動画が見つかりません")
            return []

        logger.info(f"{len(recent_videos)}本の直近動画のAnalyticsデータを取得開始...")

        # 各動画のAnalyticsデータを並列取得
        videos_data = self._fetch_videos_analytics_parallel(
            recent_videos, start_date, end_date, "strategic_analytics.recent_videos_loop"
        )

        # 再生回数で降順ソート
        videos_data.sort(key=lambda x: x.get("views", 0), reverse=True)
        self._add_subscriber_conversion_rates(videos_data)

        logger.info(f"直近動画Analytics取得完了: {len(videos_data)}本")
        return videos_data

    def _fetch_videos_analytics_parallel(
        self,
        videos: List[Dict],
        start_date: str,
        end_date: str,
        section_label: str,
    ) -> List[Dict]:
        """動画リストに対し `get_video_analytics_by_id` を `ThreadPoolExecutor` で並列実行する.

        `get_video_analytics_by_id` は HttpError を内部で catch し、`error` キー付きの
        ゼロ値 dict を返すため、worker レベルでの partial failure は既に degrade 済み。
        Future 側では `fut.result()` の予期せぬ例外のみ catch して `logger.error` でスキップする。

        Args:
            videos: video_id を含む動画 dict のリスト
            start_date: 分析開始日 (YYYY-MM-DD)
            end_date: 分析終了日 (YYYY-MM-DD)
            section_label: アウター section プロファイラのラベル

        Returns:
            元動画情報と Analytics データを merge した dict のリスト（完了順、未ソート）
        """
        videos_data: List[Dict] = []
        completed = 0
        total = len(videos)

        with section(section_label, count=total):
            with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
                futures = {
                    executor.submit(self.get_video_analytics_by_id, video["video_id"], start_date, end_date): video
                    for video in videos
                }

                for future in as_completed(futures):
                    video = futures[future]
                    completed += 1
                    logger.info(f"[{completed}/{total}] {video['title'][:50]}...")

                    try:
                        with section("strategic_analytics.get_video_analytics_by_id"):
                            analytics_data = future.result()
                    except Exception as e:
                        logger.error(f"動画 {video['video_id']} の analytics 取得に失敗: {e}")
                        continue

                    combined_data = {**video, **analytics_data}
                    self._add_subscriber_conversion_rates([combined_data])
                    videos_data.append(combined_data)

                    # 進行状況表示（10件ごと）
                    if completed % 10 == 0:
                        logger.info(f"{completed}本完了...")

        return videos_data
