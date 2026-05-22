"""comment fetcher の top-level / reply 取得テスト."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from youtube_automation.utils.comments.fetcher import fetch_top_level_comments
from youtube_automation.utils.exceptions import YouTubeAPIError


def _top_level_item(
    *,
    comment_id: str,
    text: str,
    author: str = "Top Author",
    published_at: str = "2026-05-01T00:00:00Z",
    can_reply: bool = True,
    total_reply_count: int = 0,
    moderation_status: str | None = None,
    replies: list[dict] | None = None,
) -> dict:
    item = {
        "snippet": {
            "canReply": can_reply,
            "totalReplyCount": total_reply_count,
            "topLevelComment": {
                "id": comment_id,
                "snippet": {
                    "authorDisplayName": author,
                    "textOriginal": text,
                    "publishedAt": published_at,
                    "moderationStatus": moderation_status,
                },
            },
        }
    }
    if replies is not None:
        item["replies"] = {"comments": replies}
    return item


def _reply_item(
    *,
    comment_id: str,
    text: str,
    author: str = "Reply Author",
    published_at: str = "2026-05-01T00:00:00Z",
    moderation_status: str | None = None,
) -> dict:
    return {
        "id": comment_id,
        "snippet": {
            "authorDisplayName": author,
            "textOriginal": text,
            "publishedAt": published_at,
            "moderationStatus": moderation_status,
        },
    }


def _http_error(status: int, message: str) -> HttpError:
    return HttpError(Response({"status": str(status)}), f'{{"error": {{"message": "{message}"}}}}'.encode())


def _mock_youtube(*, thread_pages: list[dict], reply_pages_by_parent: dict[str, list[dict]] | None = None) -> MagicMock:
    yt = MagicMock()
    thread_calls: list[dict] = []
    reply_calls: list[dict] = []
    reply_pages_by_parent = reply_pages_by_parent or {}

    def _thread_list(**kwargs):
        thread_calls.append(kwargs)
        response = thread_pages[len(thread_calls) - 1]
        result = MagicMock()
        if isinstance(response, Exception):
            result.execute.side_effect = response
        else:
            result.execute.return_value = response
        return result

    def _reply_list(**kwargs):
        reply_calls.append(kwargs)
        parent_id = kwargs["parentId"]
        pages = reply_pages_by_parent[parent_id]
        index = sum(1 for call in reply_calls if call["parentId"] == parent_id) - 1
        response = pages[index]
        result = MagicMock()
        if isinstance(response, Exception):
            result.execute.side_effect = response
        else:
            result.execute.return_value = response
        return result

    yt.commentThreads.return_value.list.side_effect = _thread_list
    yt.comments.return_value.list.side_effect = _reply_list
    yt._thread_calls = thread_calls
    yt._reply_calls = reply_calls
    return yt


def test_fetch_top_level_comments_requests_snippet_and_replies():
    yt = _mock_youtube(
        thread_pages=[
            {"items": [_top_level_item(comment_id="top-1", text="hello")]}
        ]
    )

    comments = list(fetch_top_level_comments(yt, video_id="vid-1"))

    assert [comment.comment_id for comment in comments] == ["top-1"]
    assert yt._thread_calls[0]["part"] == "snippet,replies"


def test_fetch_top_level_comments_yields_inline_replies_after_top_level():
    yt = _mock_youtube(
        thread_pages=[
            {
                "items": [
                    _top_level_item(
                        comment_id="top-1",
                        text="top text",
                        can_reply=False,
                        total_reply_count=2,
                        replies=[
                            _reply_item(comment_id="reply-1", text="reply one"),
                            _reply_item(comment_id="reply-2", text="reply two"),
                        ],
                    )
                ]
            }
        ]
    )

    comments = list(fetch_top_level_comments(yt, video_id="vid-1"))

    assert [comment.comment_id for comment in comments] == ["top-1", "reply-1", "reply-2"]
    assert comments[0].parent_id is None
    assert comments[1].parent_id == "top-1"
    assert comments[2].parent_id == "top-1"
    assert comments[1].can_reply is False
    assert comments[1].total_reply_count == 0
    assert comments[2].total_reply_count == 0


def test_fetch_top_level_comments_uses_comments_list_when_total_reply_count_exceeds_inline_limit():
    yt = _mock_youtube(
        thread_pages=[
            {
                "items": [
                    _top_level_item(
                        comment_id="top-1",
                        text="top text",
                        total_reply_count=6,
                        replies=[_reply_item(comment_id="inline-ignored", text="inline")],
                    )
                ]
            }
        ],
        reply_pages_by_parent={
            "top-1": [
                {
                    "items": [
                        _reply_item(comment_id="reply-1", text="reply one"),
                        _reply_item(comment_id="reply-2", text="reply two"),
                    ],
                    "nextPageToken": "page-2",
                },
                {
                    "items": [
                        _reply_item(comment_id="reply-3", text="reply three"),
                    ]
                },
            ]
        },
    )

    comments = list(fetch_top_level_comments(yt, video_id="vid-1"))

    assert [comment.comment_id for comment in comments] == ["top-1", "reply-1", "reply-2", "reply-3"]
    assert [call["parentId"] for call in yt._reply_calls] == ["top-1", "top-1"]
    assert yt._reply_calls[0]["part"] == "snippet"
    assert yt._reply_calls[0]["textFormat"] == "plainText"
    assert yt._reply_calls[1]["pageToken"] == "page-2"


def test_fetch_top_level_comments_applies_since_filter_to_top_level_and_replies():
    yt = _mock_youtube(
        thread_pages=[
            {
                "items": [
                    _top_level_item(
                        comment_id="top-old",
                        text="old top",
                        published_at="2026-05-01T00:00:00Z",
                        total_reply_count=1,
                        replies=[
                            _reply_item(
                                comment_id="reply-on-old-thread-new",
                                text="reply on old thread",
                                published_at="2026-05-04T12:00:00Z",
                            )
                        ],
                    ),
                    _top_level_item(
                        comment_id="top-new",
                        text="new top",
                        published_at="2026-05-03T00:00:00Z",
                        total_reply_count=2,
                        replies=[
                            _reply_item(
                                comment_id="reply-old",
                                text="old reply",
                                published_at="2026-05-01T12:00:00Z",
                            ),
                            _reply_item(
                                comment_id="reply-new",
                                text="new reply",
                                published_at="2026-05-04T00:00:00Z",
                            ),
                        ],
                    ),
                ]
            }
        ]
    )

    comments = list(
        fetch_top_level_comments(
            yt,
            video_id="vid-1",
            since=datetime(2026, 5, 2, tzinfo=timezone.utc),
        )
    )

    assert [comment.comment_id for comment in comments] == [
        "reply-on-old-thread-new",
        "top-new",
        "reply-new",
    ]


def test_fetch_top_level_comments_stops_at_max_results_even_mid_replies():
    yt = _mock_youtube(
        thread_pages=[
            {
                "items": [
                    _top_level_item(
                        comment_id="top-1",
                        text="top text",
                        total_reply_count=3,
                        replies=[
                            _reply_item(comment_id="reply-1", text="reply one"),
                            _reply_item(comment_id="reply-2", text="reply two"),
                            _reply_item(comment_id="reply-3", text="reply three"),
                        ],
                    )
                ]
            }
        ]
    )

    comments = list(fetch_top_level_comments(yt, video_id="vid-1", max_results=3))

    assert [comment.comment_id for comment in comments] == ["top-1", "reply-1", "reply-2"]


def test_fetch_top_level_comments_wraps_comments_list_http_error():
    yt = _mock_youtube(
        thread_pages=[
            {
                "items": [
                    _top_level_item(
                        comment_id="top-1",
                        text="top text",
                        total_reply_count=6,
                    )
                ]
            }
        ],
        reply_pages_by_parent={"top-1": [_http_error(500, "reply boom")]},
    )

    with pytest.raises(YouTubeAPIError, match="comments.list 失敗 \\(parent_id=top-1\\)"):
        list(fetch_top_level_comments(yt, video_id="vid-1"))
