"""自チャンネル動画のコメント取得（YouTube Data API v3 commentThreads.list / comments.list）."""

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
    """YouTube コメント 1 件（top-level または reply）."""

    comment_id: str
    video_id: str
    author: str
    text: str
    published_at: str
    moderation_status: str | None
    can_reply: bool
    total_reply_count: int
    parent_id: str | None = None


_THREAD_PART = "snippet,replies"
_REPLY_PART = "snippet"
_TEXT_FORMAT = "plainText"
_INLINE_REPLY_LIMIT = 5


def _passed_since(*, published_at: str, since: datetime | None) -> bool:
    if since is None or not published_at:
        return True
    try:
        published_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return published_dt >= since


def _iter_all_replies(youtube, *, parent_id: str) -> Iterator[dict]:
    next_page_token: str | None = None
    while True:
        try:
            response = (
                youtube.comments()
                .list(
                    part=_REPLY_PART,
                    parentId=parent_id,
                    maxResults=100,
                    pageToken=next_page_token,
                    textFormat=_TEXT_FORMAT,
                )
                .execute()
            )
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, f"comments.list 失敗 (parent_id={parent_id})") from e

        yield from response.get("items", [])

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            return


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
                    part=_THREAD_PART,
                    videoId=video_id,
                    maxResults=min(page_size, max_results - yielded),
                    pageToken=next_page_token,
                    textFormat=_TEXT_FORMAT,
                )
                .execute()
            )
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, f"commentThreads.list 失敗 (video_id={video_id})") from e

        for item in response.get("items", []):
            thread_snippet = item["snippet"]
            top = thread_snippet["topLevelComment"]
            snippet = top["snippet"]
            published = snippet.get("publishedAt", "")
            top_passed = _passed_since(published_at=published, since=since)
            can_reply = bool(thread_snippet.get("canReply", True))
            total_reply_count = int(thread_snippet.get("totalReplyCount", 0))
            if top_passed:
                yield FetchedComment(
                    comment_id=top["id"],
                    video_id=video_id,
                    author=snippet.get("authorDisplayName", ""),
                    text=snippet.get("textOriginal", snippet.get("textDisplay", "")),
                    published_at=published,
                    moderation_status=snippet.get("moderationStatus"),
                    can_reply=can_reply,
                    total_reply_count=total_reply_count,
                    parent_id=None,
                )
                yielded += 1
                if yielded >= max_results:
                    return

            if total_reply_count == 0:
                continue
            if total_reply_count > _INLINE_REPLY_LIMIT:
                replies = _iter_all_replies(youtube, parent_id=top["id"])
            else:
                replies = item.get("replies", {}).get("comments", [])

            for reply in replies:
                reply_snippet = reply["snippet"]
                reply_published = reply_snippet.get("publishedAt", "")
                if not _passed_since(published_at=reply_published, since=since):
                    continue
                yield FetchedComment(
                    comment_id=reply["id"],
                    video_id=video_id,
                    author=reply_snippet.get("authorDisplayName", ""),
                    text=reply_snippet.get("textOriginal", reply_snippet.get("textDisplay", "")),
                    published_at=reply_published,
                    moderation_status=reply_snippet.get("moderationStatus"),
                    can_reply=can_reply,
                    total_reply_count=0,
                    parent_id=top["id"],
                )
                yielded += 1
                if yielded >= max_results:
                    return

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            return
