"""
動画一覧取得 Mixin
YouTubeAnalyticsCollector のチャンネル動画リスト取得メソッド群
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict, List

from youtube_automation.utils.exceptions import YouTubeAPIError
from youtube_automation.utils.retry import execute_with_retry

if TYPE_CHECKING:
    from .analytics_base import AnalyticsBase  # noqa: F401


logger = logging.getLogger(__name__)


class VideoListingMixin:
    """動画一覧取得の Mixin"""

    def get_all_channel_videos(self, refresh: bool = False) -> List[Dict]:
        """
        チャンネルの全動画リストを取得（YouTube Data API v3使用）

        1 プロセス内では動画リストが変わらない前提でインスタンスキャッシュする。
        空リストはキャッシュしない（エラー時の再試行余地を残すため）。

        Args:
            refresh (bool): True の場合キャッシュを無視して再取得する

        Returns:
            List[Dict]: 動画情報リスト
        """
        cached = getattr(self, "_all_videos_cache", None)
        if not refresh and cached is not None:
            return cached

        if not self.youtube_service:
            self.initialize()

        logger.info("チャンネル全動画リスト取得中...")

        try:
            # チャンネルのアップロード済みプレイリストIDを取得
            request = self.youtube_service.channels().list(part="contentDetails", id=self.channel_id)
            channel_response = execute_with_retry(request, "YouTube Data API request failed")

            uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

            # 全動画を取得
            videos = []
            next_page_token = None

            while True:
                # プレイリストのアイテムを取得
                request = self.youtube_service.playlistItems().list(
                    part="snippet,contentDetails",
                    playlistId=uploads_playlist_id,
                    maxResults=50,
                    pageToken=next_page_token,
                )
                playlist_response = execute_with_retry(request, "YouTube Analytics API request failed")

                for item in playlist_response["items"]:
                    video_info = {
                        "video_id": item["contentDetails"]["videoId"],
                        "title": item["snippet"]["title"],
                        "published_at": item["snippet"]["publishedAt"],
                        "description": (
                            item["snippet"]["description"][:100] + "..."
                            if len(item["snippet"]["description"]) > 100
                            else item["snippet"]["description"]
                        ),
                    }
                    videos.append(video_info)

                next_page_token = playlist_response.get("nextPageToken")
                if not next_page_token:
                    break

                logger.info(f"{len(videos)}本の動画を取得済み...")

            logger.info(f"全動画取得完了: {len(videos)}本")
            if videos:
                self._all_videos_cache = videos
            return videos

        except YouTubeAPIError as e:
            logger.error(f"YouTube API エラー（動画リスト取得）: {e}")
            raise YouTubeAPIError(str(e), status_code=e.status_code, reason=e.reason) from e

    def get_recent_videos(self, days: int = 30) -> List[Dict]:
        """
        直近N日間の投稿動画を取得

        Args:
            days (int): 過去の日数（デフォルト30日）

        Returns:
            List[Dict]: 直近投稿動画リスト
        """
        if not self.youtube_service:
            self.initialize()

        logger.info(f"直近{days}日間の投稿動画を取得中...")

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        # 全動画リストを取得
        all_videos = self.get_all_channel_videos()

        # 直近の動画をフィルタリング
        recent_videos = []
        for video in all_videos:
            # ISO形式の日付をパース
            published_date = datetime.fromisoformat(video["published_at"].replace("Z", "+00:00"))

            if published_date >= cutoff_date:
                recent_videos.append(video)

        # 投稿日時で降順ソート（新しい順）
        recent_videos.sort(key=lambda x: x["published_at"], reverse=True)

        logger.info(f"直近{days}日間の投稿動画取得完了: {len(recent_videos)}本")
        return recent_videos

    def get_scheduled_video_count(self, now: datetime | None = None) -> int:
        """YouTube 上で未来の ``status.publishAt`` を持つ動画数を返す。"""
        if not self.youtube_service:
            self.initialize()

        reference_time = now or datetime.now(timezone.utc)
        if reference_time.tzinfo is None:
            raise ValueError("now は timezone-aware datetime でなければなりません")

        video_ids = [video["video_id"] for video in self.get_all_channel_videos()]
        scheduled_count = 0
        for start in range(0, len(video_ids), 50):
            batch = video_ids[start : start + 50]
            request = self.youtube_service.videos().list(part="status", id=",".join(batch))
            response = execute_with_retry(request, "scheduled videos.list failed")
            for item in response.get("items", []):
                publish_at = item.get("status", {}).get("publishAt")
                if not isinstance(publish_at, str):
                    continue
                try:
                    scheduled_at = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
                except ValueError:
                    logger.warning("不正な status.publishAt をスキップ: %s", publish_at)
                    continue
                if scheduled_at > reference_time:
                    scheduled_count += 1
        return scheduled_count
