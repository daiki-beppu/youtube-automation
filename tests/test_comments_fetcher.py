"""fetch_comments のユニットテスト."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from youtube_automation.utils.comments.fetcher import fetch_comments


def _make_thread_item(
    *,
    thread_id: str,
    text: str,
    can_reply: bool = True,
    total_reply_count: int = 0,
    published_at: str = "2026-05-01T00:00:00Z",
    author: str = "Author",
    author_channel_id: str | None = "UCauthor",
    moderation_status: str | None = None,
    replies: list[dict] | None = None,
) -> dict:
    item: dict = {
        "snippet": {
            "canReply": can_reply,
            "totalReplyCount": total_reply_count,
            "topLevelComment": {
                "id": thread_id,
                "snippet": {
                    "authorDisplayName": author,
                    "authorChannelId": {"value": author_channel_id} if author_channel_id else {},
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


def _make_reply_item(
    *,
    reply_id: str,
    text: str,
    parent_id: str,
    published_at: str = "2026-05-02T00:00:00Z",
    author: str = "Replier",
    author_channel_id: str | None = "UCreplier",
) -> dict:
    return {
        "id": reply_id,
        "snippet": {
            "authorDisplayName": author,
            "authorChannelId": {"value": author_channel_id} if author_channel_id else {},
            "textOriginal": text,
            "publishedAt": published_at,
            "parentId": parent_id,
        },
    }


def _mock_youtube_threads(items: list[dict], next_page_token: str | None = None) -> MagicMock:
    yt = MagicMock()
    yt.commentThreads.return_value.list.return_value.execute.return_value = {
        "items": items,
        **({"nextPageToken": next_page_token} if next_page_token else {}),
    }
    return yt


def test_top_level_comment_has_parent_id_none():
    # Given: 返信なしのトップレベルコメント 1 件
    yt = _mock_youtube_threads([_make_thread_item(thread_id="t1", text="hello")])

    # When
    comments = list(fetch_comments(yt, video_id="v1"))

    # Then: parent_id は None
    assert len(comments) == 1
    assert comments[0].comment_id == "t1"
    assert comments[0].parent_id is None
    assert comments[0].video_id == "v1"


def test_top_level_comment_includes_author_channel_id():
    # Given: author_channel_id を持つコメント
    yt = _mock_youtube_threads(
        [_make_thread_item(thread_id="t1", text="hi", author_channel_id="UCfoo")]
    )

    # When
    comments = list(fetch_comments(yt, video_id="v1"))

    # Then
    assert comments[0].author_channel_id == "UCfoo"


def test_inline_replies_are_yielded_with_parent_id():
    # Given: totalReplyCount=2 で replies.comments に 2 件含まれるスレッド
    thread = _make_thread_item(
        thread_id="t1",
        text="top",
        total_reply_count=2,
        replies=[
            _make_reply_item(reply_id="r1", text="reply1", parent_id="t1"),
            _make_reply_item(reply_id="r2", text="reply2", parent_id="t1"),
        ],
    )
    yt = _mock_youtube_threads([thread])

    # When
    comments = list(fetch_comments(yt, video_id="v1"))

    # Then: top-level + 2 replies
    assert len(comments) == 3
    top = next(c for c in comments if c.comment_id == "t1")
    assert top.parent_id is None

    replies = [c for c in comments if c.comment_id in {"r1", "r2"}]
    assert len(replies) == 2
    assert all(r.parent_id == "t1" for r in replies)
    assert all(r.video_id == "v1" for r in replies)


def test_inline_replies_inherit_thread_can_reply():
    # Given: canReply=False のスレッドに返信あり
    thread = _make_thread_item(
        thread_id="t1",
        text="top",
        can_reply=False,
        total_reply_count=1,
        replies=[_make_reply_item(reply_id="r1", text="reply", parent_id="t1")],
    )
    yt = _mock_youtube_threads([thread])

    # When
    comments = list(fetch_comments(yt, video_id="v1"))

    # Then: reply も can_reply=False を引き継ぐ
    reply = next(c for c in comments if c.comment_id == "r1")
    assert reply.can_reply is False


def test_paginated_replies_fetched_when_total_reply_count_exceeds_five():
    # Given: totalReplyCount=7 (>5) のスレッド → comments.list でページング
    thread = _make_thread_item(
        thread_id="t1",
        text="top",
        total_reply_count=7,
        # inline replies は含まれない（API は最大5件しか返さない）
    )
    yt = _mock_youtube_threads([thread])

    # comments().list() モック：7件を1ページで返す
    paginated_replies = [
        _make_reply_item(reply_id=f"r{i}", text=f"reply{i}", parent_id="t1")
        for i in range(7)
    ]
    yt.comments.return_value.list.return_value.execute.return_value = {
        "items": paginated_replies,
    }

    # When
    comments = list(fetch_comments(yt, video_id="v1"))

    # Then: top + 7 replies
    assert len(comments) == 8
    reply_ids = {c.comment_id for c in comments if c.parent_id == "t1"}
    assert reply_ids == {f"r{i}" for i in range(7)}

    # comments().list が parentId=t1 で呼ばれたことを確認
    yt.comments.return_value.list.assert_called_once()
    call_kwargs = yt.comments.return_value.list.call_args.kwargs
    assert call_kwargs["parentId"] == "t1"


def test_paginated_replies_handles_multiple_pages():
    # Given: totalReplyCount=6 で comments.list が 2ページに分かれる
    thread = _make_thread_item(thread_id="t1", text="top", total_reply_count=6)
    yt = _mock_youtube_threads([thread])

    page1_replies = [_make_reply_item(reply_id=f"r{i}", text=f"r{i}", parent_id="t1") for i in range(3)]
    page2_replies = [_make_reply_item(reply_id=f"r{i}", text=f"r{i}", parent_id="t1") for i in range(3, 6)]

    yt.comments.return_value.list.return_value.execute.side_effect = [
        {"items": page1_replies, "nextPageToken": "page2token"},
        {"items": page2_replies},
    ]

    # When
    comments = list(fetch_comments(yt, video_id="v1"))

    # Then: top + 6 replies
    assert len(comments) == 7
    assert yt.comments.return_value.list.call_count == 2


def test_since_filter_excludes_old_top_level_comments():
    from datetime import timezone

    since = "2026-05-10T00:00:00+00:00"
    # Given: 新旧混在のコメント
    items = [
        _make_thread_item(thread_id="old", text="old", published_at="2026-05-01T00:00:00Z"),
        _make_thread_item(thread_id="new", text="new", published_at="2026-05-11T00:00:00Z"),
    ]
    yt = _mock_youtube_threads(items)

    # When
    from datetime import datetime

    since_dt = datetime.fromisoformat(since)
    comments = list(fetch_comments(yt, video_id="v1", since=since_dt))

    # Then: 古いコメントはスキップ
    ids = {c.comment_id for c in comments}
    assert "old" not in ids
    assert "new" in ids


def test_since_filter_applies_to_inline_replies():
    from datetime import datetime

    since_dt = datetime.fromisoformat("2026-05-10T00:00:00+00:00")
    thread = _make_thread_item(
        thread_id="t1",
        text="top",
        total_reply_count=2,
        replies=[
            _make_reply_item(reply_id="old_reply", text="old", parent_id="t1", published_at="2026-05-01T00:00:00Z"),
            _make_reply_item(reply_id="new_reply", text="new", parent_id="t1", published_at="2026-05-11T00:00:00Z"),
        ],
    )
    yt = _mock_youtube_threads([thread])

    # When
    comments = list(fetch_comments(yt, video_id="v1", since=since_dt))

    # Then: 古い返信はスキップ
    ids = {c.comment_id for c in comments}
    assert "old_reply" not in ids
    assert "new_reply" in ids


def test_max_results_limits_top_level_count():
    # Given: 5 件のスレッド
    items = [
        _make_thread_item(thread_id=f"t{i}", text=f"text{i}")
        for i in range(5)
    ]
    yt = _mock_youtube_threads(items)

    # When: max_results=3
    comments = list(fetch_comments(yt, video_id="v1", max_results=3))

    # Then: top-level は 3 件まで
    top_level = [c for c in comments if c.parent_id is None]
    assert len(top_level) == 3


def test_uses_snippet_replies_part():
    # Given
    yt = _mock_youtube_threads([])

    # When
    list(fetch_comments(yt, video_id="v1"))

    # Then: part="snippet,replies" で呼ばれていること
    call_kwargs = yt.commentThreads.return_value.list.call_args.kwargs
    assert call_kwargs["part"] == "snippet,replies"


def test_no_replies_when_total_reply_count_zero():
    # Given: 返信なし
    thread = _make_thread_item(thread_id="t1", text="hello", total_reply_count=0)
    yt = _mock_youtube_threads([thread])

    # When
    comments = list(fetch_comments(yt, video_id="v1"))

    # Then: top-level のみ。comments.list は呼ばれない
    assert len(comments) == 1
    yt.comments.assert_not_called()


def test_reply_has_correct_fields():
    # Given
    thread = _make_thread_item(
        thread_id="t1",
        text="top",
        total_reply_count=1,
        replies=[
            _make_reply_item(
                reply_id="r1",
                text="nice!",
                parent_id="t1",
                author="Viewer",
                author_channel_id="UCviewer",
                published_at="2026-05-05T12:00:00Z",
            )
        ],
    )
    yt = _mock_youtube_threads([thread])

    # When
    comments = list(fetch_comments(yt, video_id="v1"))

    # Then: reply フィールドを確認
    reply = next(c for c in comments if c.comment_id == "r1")
    assert reply.text == "nice!"
    assert reply.author == "Viewer"
    assert reply.author_channel_id == "UCviewer"
    assert reply.published_at == "2026-05-05T12:00:00Z"
    assert reply.parent_id == "t1"
    assert reply.total_reply_count == 0
    assert reply.video_id == "v1"


# --- リグレッション防止テスト ---


def test_fetch_top_level_comments_name_does_not_exist():
    """旧名 fetch_top_level_comments がエイリアスとして残存しないことを確認."""
    import youtube_automation.utils.comments.fetcher as fetcher

    assert not hasattr(fetcher, "fetch_top_level_comments")


def test_fetcher_module_has_no_unused_logger():
    """未使用の logger が fetcher モジュールに残存しないことを確認."""
    import youtube_automation.utils.comments.fetcher as fetcher

    assert not hasattr(fetcher, "logger")
