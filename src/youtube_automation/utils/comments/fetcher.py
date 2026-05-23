"""自チャンネル動画のコメント取得（YouTube Data API v3 commentThreads.list + comments.list）."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

from googleapiclient.errors import HttpError

from youtube_automation.utils.exceptions import YouTubeAPIError

# YouTube API が commentThreads.list の replies.comments に含める最大件数
_INLINE_REPLY_LIMIT = 5


@dataclass(frozen=True)
class FetchedComment:
    """commentThreads.list / comments.list から取得したコメント 1 件."""

    comment_id: str
    video_id: str
    author: str
    author_channel_id: str | None
    text: str
    published_at: str
    moderation_status: str | None
    can_reply: bool
    total_reply_count: int
    parent_id: str | None  # top-level なら None、reply なら親 comment_id


def _parse_published_at(published: str) -> datetime | None:
    try:
        return datetime.fromisoformat(published.replace("Z", "+00:00"))
    except ValueError:
        return None


def _after_since(published: str, since: datetime | None) -> bool:
    """since が未設定、またはコメントが since 以降かどうかを返す.

    日付パース失敗・空文字列は True を返す（スキップしない方向に倒す）。
    """
    if since is None or not published:
        return True
    pub_dt = _parse_published_at(published)
    return pub_dt is None or pub_dt >= since


def _build_reply_comment(
    item: dict,
    *,
    video_id: str,
    can_reply: bool,
    parent_id: str,
) -> FetchedComment:
    snippet = item["snippet"]
    return FetchedComment(
        comment_id=item["id"],
        video_id=video_id,
        author=snippet.get("authorDisplayName", ""),
        author_channel_id=snippet.get("authorChannelId", {}).get("value"),
        text=snippet.get("textOriginal", snippet.get("textDisplay", "")),
        published_at=snippet.get("publishedAt", ""),
        moderation_status=snippet.get("moderationStatus"),
        can_reply=can_reply,
        total_reply_count=0,
        parent_id=parent_id,
    )


def _fetch_replies_paginated(
    youtube,
    *,
    top_comment_id: str,
    video_id: str,
    can_reply: bool,
    since: datetime | None,
) -> Iterator[FetchedComment]:
    """comments.list で返信を全件ページングして yield する.

    totalReplyCount > 5 で API が replies を最大 5 件に切り詰める場合に呼ぶ。
    """
    page_token: str | None = None
    while True:
        try:
            response = (
                youtube.comments()
                .list(
                    part="snippet",
                    parentId=top_comment_id,
                    maxResults=100,
                    pageToken=page_token,
                    textFormat="plainText",
                )
                .execute()
            )
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(
                e, f"comments.list 失敗 (parentId={top_comment_id})"
            ) from e

        for item in response.get("items", []):
            if _after_since(item["snippet"].get("publishedAt", ""), since):
                yield _build_reply_comment(
                    item,
                    video_id=video_id,
                    can_reply=can_reply,
                    parent_id=top_comment_id,
                )

        page_token = response.get("nextPageToken")
        if not page_token:
            return


def _iter_inline_replies(
    reply_items: list[dict],
    *,
    video_id: str,
    can_reply: bool,
    parent_id: str,
    since: datetime | None,
) -> Iterator[FetchedComment]:
    """commentThreads.list の replies.comments から返信を yield する."""
    for item in reply_items:
        if _after_since(item["snippet"].get("publishedAt", ""), since):
            yield _build_reply_comment(
                item,
                video_id=video_id,
                can_reply=can_reply,
                parent_id=parent_id,
            )


def _iter_thread(
    youtube,
    item: dict,
    *,
    video_id: str,
    since: datetime | None,
) -> Iterator[FetchedComment]:
    """1 つのスレッドアイテムから top-level + replies を yield する."""
    top = item["snippet"]["topLevelComment"]
    snippet = top["snippet"]
    thread_can_reply = bool(item["snippet"].get("canReply", True))
    total_reply_count = int(item["snippet"].get("totalReplyCount", 0))
    published = snippet.get("publishedAt", "")

    if _after_since(published, since):
        yield FetchedComment(
            comment_id=top["id"],
            video_id=video_id,
            author=snippet.get("authorDisplayName", ""),
            author_channel_id=snippet.get("authorChannelId", {}).get("value"),
            text=snippet.get("textOriginal", snippet.get("textDisplay", "")),
            published_at=published,
            moderation_status=snippet.get("moderationStatus"),
            can_reply=thread_can_reply,
            total_reply_count=total_reply_count,
            parent_id=None,
        )

    if total_reply_count > _INLINE_REPLY_LIMIT:
        yield from _fetch_replies_paginated(
            youtube,
            top_comment_id=top["id"],
            video_id=video_id,
            can_reply=thread_can_reply,
            since=since,
        )
    else:
        yield from _iter_inline_replies(
            item.get("replies", {}).get("comments", []),
            video_id=video_id,
            can_reply=thread_can_reply,
            parent_id=top["id"],
            since=since,
        )


def fetch_comments(
    youtube,
    *,
    video_id: str,
    max_results: int = 100,
    since: datetime | None = None,
    page_size: int = 100,
) -> Iterator[FetchedComment]:
    """指定動画のコメントスレッドを generator で返す（top-level + replies）.

    Args:
        youtube: `youtube_service.get_youtube()` / `ServiceRegistry.youtube`
        video_id: 対象動画 ID
        max_results: トップレベルコメントの返却上限（スレッド数）
        since: これより新しいコメントのみ対象（`publishedAt` 比較）
        page_size: 1 ページあたりのスレッド取得件数（YouTube API 最大 100）

    Yields:
        FetchedComment（top-level は parent_id=None、reply は parent_id=top_comment_id）

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
                    part="snippet,replies",
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
            for comment in _iter_thread(youtube, item, video_id=video_id, since=since):
                yield comment
                if comment.parent_id is None:
                    yielded += 1
            if yielded >= max_results:
                return

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            return
