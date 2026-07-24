"""utils/streaming/monthly_archive.py のユニットテスト。

要件 R11: 月間アーカイブ件数 (理論値 60 本/月) を YouTube Data API から取得する。

設計:
- `count_archives(youtube_service, channel_id, year, month)` は search().list() を
  publishedAfter / publishedBefore で絞り、ページングしながら件数を集計する。
- 純粋なカウントのみを返す (件数のみ。動画 ID リストは別関数 or 内部利用)。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from youtube_automation.infrastructure.errors import YouTubeAPIError
from youtube_automation.utils.streaming import monthly_archive


def _make_service(pages: list[dict]):
    """search().list().execute() を pages の順に返す MagicMock。"""
    service = MagicMock()
    execute_mock = service.search.return_value.list.return_value.execute
    execute_mock.side_effect = pages
    return service


def test_count_archives_single_page():
    """Given 1 ページに 3 件
    When count_archives を呼ぶ
    Then 3 を返す。
    """
    service = _make_service(
        [
            {"items": [{"id": {"videoId": "v1"}}, {"id": {"videoId": "v2"}}, {"id": {"videoId": "v3"}}]},
        ]
    )
    got = monthly_archive.count_archives(service, channel_id="UC_X", year=2026, month=4)
    assert got == 3


def test_count_archives_paginates():
    """Given 1 ページ目に nextPageToken / 2 ページ目で終了
    When count_archives を呼ぶ
    Then 2 ページ分の合計件数 (3 + 2 = 5)。
    """
    service = _make_service(
        [
            {
                "items": [{"id": {"videoId": "v1"}}, {"id": {"videoId": "v2"}}, {"id": {"videoId": "v3"}}],
                "nextPageToken": "TOK",
            },
            {"items": [{"id": {"videoId": "v4"}}, {"id": {"videoId": "v5"}}]},
        ]
    )
    got = monthly_archive.count_archives(service, channel_id="UC_X", year=2026, month=4)
    assert got == 5


def test_count_archives_zero_when_no_items():
    """Given items が空
    When count_archives を呼ぶ
    Then 0 (境界値)。
    """
    service = _make_service([{"items": []}])
    assert monthly_archive.count_archives(service, channel_id="UC_X", year=2026, month=4) == 0


def test_count_archives_uses_published_after_and_before_for_target_month():
    """Given year=2026, month=4
    When count_archives を呼ぶ
    Then search().list(publishedAfter="2026-04-01T00:00:00Z",
                        publishedBefore="2026-05-01T00:00:00Z") で呼ばれる。
    """
    service = _make_service([{"items": []}])
    monthly_archive.count_archives(service, channel_id="UC_X", year=2026, month=4)

    list_calls = service.search.return_value.list.call_args_list
    # 最後の有効な呼び出しを検査
    kwargs = list_calls[-1].kwargs
    assert kwargs["channelId"] == "UC_X"
    assert kwargs["type"] == "video"
    assert kwargs["publishedAfter"].startswith("2026-04-01T00:00:00")
    assert kwargs["publishedBefore"].startswith("2026-05-01T00:00:00")


def test_count_archives_uses_correct_year_boundary_for_december():
    """Given year=2026, month=12 (年跨ぎ)
    When count_archives を呼ぶ
    Then publishedBefore="2027-01-01T00:00:00Z"。
    """
    service = _make_service([{"items": []}])
    monthly_archive.count_archives(service, channel_id="UC_X", year=2026, month=12)

    list_calls = service.search.return_value.list.call_args_list
    kwargs = list_calls[-1].kwargs
    assert kwargs["publishedAfter"].startswith("2026-12-01T00:00:00")
    assert kwargs["publishedBefore"].startswith("2027-01-01T00:00:00")


def test_count_archives_passes_page_token_on_subsequent_calls():
    """Given 2 ページにまたがる
    When count_archives を呼ぶ
    Then 2 回目の list() に pageToken="TOK" が付く。
    """
    service = _make_service(
        [
            {"items": [{"id": {"videoId": "v1"}}], "nextPageToken": "TOK"},
            {"items": [{"id": {"videoId": "v2"}}]},
        ]
    )
    monthly_archive.count_archives(service, channel_id="UC_X", year=2026, month=4)
    list_calls = service.search.return_value.list.call_args_list
    second_kwargs = list_calls[-1].kwargs
    assert second_kwargs.get("pageToken") == "TOK"


def test_count_archives_wraps_http_error_as_youtube_api_error():
    """Given search().list().execute() が HttpError
    When count_archives を呼ぶ
    Then YouTubeAPIError に変換 (生 HttpError を上に漏らさない設計)。
    """
    service = MagicMock()
    service.search.return_value.list.return_value.execute.side_effect = HttpError(
        MagicMock(status=403), b"quotaExceeded"
    )
    with pytest.raises(YouTubeAPIError):
        monthly_archive.count_archives(service, channel_id="UC_X", year=2026, month=4)


def test_count_archives_uses_for_mine_when_channel_id_none():
    """Given channel_id=None (CLI が --channel-id 未指定の経路)
    When count_archives を呼ぶ
    Then search().list() に forMine=True が渡され、channelId は付かない。

    回帰防止: ARCH-NEW-archive-counter-forMine-untested (family_tag=test-coverage-gap)。
    """
    service = _make_service([{"items": []}])
    monthly_archive.count_archives(service, channel_id=None, year=2026, month=4)

    kwargs = service.search.return_value.list.call_args_list[-1].kwargs
    assert kwargs.get("forMine") is True
    assert "channelId" not in kwargs
