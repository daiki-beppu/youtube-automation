"""自チャンネル動画のコメント取得（YouTube Data API v3 commentThreads.list）."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

from googleapiclient.errors import HttpError

from youtube_automation.utils.exceptions import YouTubeAPIError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchedComment:
    """commentThreads.list から取得したトップレベルコメント 1 件."""

    comment_id: str
    video_id: str
    author: str
    text: str
    published_at: str
    moderation_status: str | None
    can_reply: bool
    total_reply_count: int


def fetch_top_level_comments(
    youtube,
    *,
    video_id: str,
    max_results: int = 100,
    since: datetime | None = None,
    page_size: int = 100,
) -> Iterator[FetchedComment]:
    """指定動画のトップレベルコメントを generator で返す.

    Args:
        youtube: `youtube_service.get_youtube()` / `ServiceRegistry.youtube`
        video_id: 対象動画 ID
        max_results: 返却上限（total で）。None 不可
        since: これより新しいコメントのみ対象（`publishedAt` 比較）
        page_size: 1 ページあたりの取得件数（YouTube API 最大 100）

    Yields:
        FetchedComment

    Raises:
        YouTubeAPIError: HttpError を status_code 付きでラップ
    """
    next_page_token: str | None = None
    yielded = 0
    while yielded < max_results:
        try:
            response = (
                youtube.commentThreads()
                .list(
                    part="snippet",
                    videoId=video_id,
                    maxResults=min(page_size, max_results - yielded),
                    pageToken=next_page_token,
                    textFormat="plainText",
                )
                .execute()
            )
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, f"commentThreads.list 失敗 (video_id={video_id})") from e

        for item in response.get("items", []):
            top = item["snippet"]["topLevelComment"]
            snippet = top["snippet"]
            published = snippet.get("publishedAt", "")
            if since is not None and published:
                try:
                    pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                except ValueError:
                    pub_dt = None
                if pub_dt is not None and pub_dt < since:
                    continue
            yield FetchedComment(
                comment_id=top["id"],
                video_id=video_id,
                author=snippet.get("authorDisplayName", ""),
                text=snippet.get("textOriginal", snippet.get("textDisplay", "")),
                published_at=published,
                moderation_status=snippet.get("moderationStatus"),
                can_reply=bool(item["snippet"].get("canReply", True)),
                total_reply_count=int(item["snippet"].get("totalReplyCount", 0)),
            )
            yielded += 1
            if yielded >= max_results:
                return

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            return
