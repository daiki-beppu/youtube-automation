"""YouTube Data API でアーカイブ件数を計数する（Issue #110 / R11）。

設計:
- `count_archives(service, channel_id, year, month)` は publishedAfter / publishedBefore
  で対象月を絞り、ページングしながら件数を集計する。
- `channel_id` を渡せば `channelId=<id>` で絞り込み、None なら `forMine=True` で
  認証ユーザーのチャンネルに絞る。
- HttpError は YouTubeAPIError に変換 (生の HttpError を上に漏らさない)。
"""

from __future__ import annotations

from typing import Any

from googleapiclient.errors import HttpError

from youtube_automation.infrastructure.errors import YouTubeAPIError


def _month_boundaries(year: int, month: int) -> tuple[str, str]:
    """対象月の開始・翌月開始の RFC3339 (UTC) 文字列を返す。"""
    after = f"{year:04d}-{month:02d}-01T00:00:00Z"
    if month == 12:
        before = f"{year + 1:04d}-01-01T00:00:00Z"
    else:
        before = f"{year:04d}-{month + 1:02d}-01T00:00:00Z"
    return after, before


def count_archives(service: Any, *, channel_id: str | None, year: int, month: int) -> int:
    """対象月の動画件数 (アーカイブ含む) を取得する。

    Args:
        service: YouTube Data API v3 service オブジェクト
        channel_id: 対象チャンネル ID (UC...)。None なら `forMine=True` で
            認証ユーザーのチャンネルを対象にする。
        year: 対象年
        month: 対象月 (1-12)

    Returns:
        動画件数 (件数のみ)

    Raises:
        YouTubeAPIError: HttpError を変換して raise
    """
    after, before = _month_boundaries(year, month)
    total = 0
    page_token: str | None = None
    while True:
        list_kwargs: dict[str, Any] = {
            "part": "id",
            "type": "video",
            "publishedAfter": after,
            "publishedBefore": before,
            "maxResults": 50,
        }
        if channel_id is not None:
            list_kwargs["channelId"] = channel_id
        else:
            list_kwargs["forMine"] = True
        if page_token is not None:
            list_kwargs["pageToken"] = page_token
        try:
            response = service.search().list(**list_kwargs).execute()
        except HttpError as e:
            raise YouTubeAPIError.from_http_error(e, "YouTube search().list() failed") from e

        items = response.get("items", [])
        total += len(items)
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return total
