"""channel-new のベンチマーク seed fetch ユーティリティのテスト."""

from __future__ import annotations

import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from youtube_automation.utils.channel_seed import (
    SeedChannel,
    fetch_channel_seed,
    merge_benchmark_channel,
    to_benchmark_entry,
)
from youtube_automation.utils.exceptions import ValidationError, YouTubeAPIError


def _request(response: dict) -> MagicMock:
    request = MagicMock()
    request.execute.return_value = response
    return request


def _http_error(status: int) -> HttpError:
    return HttpError(resp=MagicMock(status=status), content=b'{"error": {"message": "quotaExceeded"}}')


def _youtube_with_channels(response: dict) -> MagicMock:
    youtube = MagicMock()
    youtube.channels.return_value.list.return_value = _request(response)
    return youtube


def _channel_item(
    *,
    channel_id: str = "UC_seed",
    handle: str = "@seed",
    name: str = "Seed Channel",
    subscribers: str = "12345",
    total_videos: str = "67",
    uploads: str = "UU_seed",
) -> dict:
    return {
        "id": channel_id,
        "snippet": {"title": name, "customUrl": handle},
        "statistics": {"subscriberCount": subscribers, "videoCount": total_videos},
        "contentDetails": {"relatedPlaylists": {"uploads": uploads}},
    }


def test_fetch_channel_seed_uses_one_channels_call_and_one_playlist_items_page():
    # Given
    youtube = MagicMock()
    youtube.channels.return_value.list.return_value = _request({"items": [_channel_item()]})
    youtube.playlistItems.return_value.list.return_value = _request(
        {
            "items": [
                {"snippet": {"title": "First Video"}},
                {"snippet": {"title": "Second Video"}},
            ]
        }
    )

    # When
    seed = fetch_channel_seed(youtube, "https://www.youtube.com/channel/UC_seed", recent=10)

    # Then
    assert seed == SeedChannel(
        channel_id="UC_seed",
        handle="@seed",
        name="Seed Channel",
        subscribers=12_345,
        total_videos=67,
        uploads_playlist_id="UU_seed",
        recent_titles=("First Video", "Second Video"),
    )
    youtube.channels.return_value.list.assert_called_once_with(
        part="snippet,statistics,contentDetails",
        id="UC_seed",
    )
    youtube.playlistItems.return_value.list.assert_called_once_with(
        part="snippet",
        playlistId="UU_seed",
        maxResults=10,
    )
    youtube.videos.return_value.list.assert_not_called()


def test_fetch_channel_seed_defaults_hidden_subscriber_count_to_zero():
    # Given
    youtube = MagicMock()
    item = _channel_item(subscribers="1", total_videos="67")
    item["statistics"].pop("subscriberCount")
    youtube.channels.return_value.list.return_value = _request({"items": [item]})
    youtube.playlistItems.return_value.list.return_value = _request({"items": []})

    # When
    seed = fetch_channel_seed(youtube, "https://www.youtube.com/channel/UC_seed", recent=10)

    # Then
    assert seed.subscribers == 0
    assert seed.total_videos == 67


def test_fetch_channel_seed_reuses_handle_channels_response_for_summary():
    # Given
    youtube = MagicMock()
    youtube.channels.return_value.list.return_value = _request({"items": [_channel_item(channel_id="UC_handle")]})
    youtube.playlistItems.return_value.list.return_value = _request({"items": []})

    # When
    seed = fetch_channel_seed(youtube, "@seedhandle", recent=10)

    # Then
    assert seed.channel_id == "UC_handle"
    youtube.channels.return_value.list.assert_called_once_with(
        part="snippet,statistics,contentDetails",
        forHandle="seedhandle",
    )


def test_fetch_channel_seed_uses_for_handle_for_handle_url():
    # Given
    youtube = MagicMock()
    youtube.channels.return_value.list.return_value = _request({"items": [_channel_item(channel_id="UC_handle_url")]})
    youtube.playlistItems.return_value.list.return_value = _request({"items": []})

    # When
    seed = fetch_channel_seed(youtube, "https://www.youtube.com/@seedhandle", recent=10)

    # Then
    assert seed.channel_id == "UC_handle_url"
    youtube.channels.return_value.list.assert_called_once_with(
        part="snippet,statistics,contentDetails",
        forHandle="seedhandle",
    )
    youtube.playlistItems.return_value.list.assert_called_once_with(
        part="snippet",
        playlistId="UU_seed",
        maxResults=10,
    )


def test_fetch_channel_seed_extracts_channel_id_from_custom_url_html():
    # Given
    youtube = MagicMock()
    html = b'{"metadata":{"channelMetadataRenderer":{"externalId":"UC_custom"}}}'
    youtube.channels.return_value.list.return_value = _request({"items": [_channel_item(channel_id="UC_custom")]})
    youtube.playlistItems.return_value.list.return_value = _request({"items": []})

    # When
    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = html
        seed = fetch_channel_seed(youtube, "https://www.youtube.com/c/seed", recent=10)

    # Then
    assert seed.channel_id == "UC_custom"
    youtube.channels.return_value.list.assert_called_once_with(
        part="snippet,statistics,contentDetails",
        id="UC_custom",
    )
    youtube.playlistItems.return_value.list.assert_called_once_with(
        part="snippet",
        playlistId="UU_seed",
        maxResults=10,
    )


def test_fetch_channel_seed_wraps_html_fetch_error_with_timeout():
    # Given
    youtube = MagicMock()

    # When/Then
    with patch("youtube_automation.utils.channel_seed.urllib.request.urlopen") as urlopen:
        urlopen.side_effect = urllib.error.URLError("timeout")
        with pytest.raises(YouTubeAPIError):
            fetch_channel_seed(youtube, "https://www.youtube.com/c/seed", recent=10)
    urlopen.assert_called_once_with("https://www.youtube.com/c/seed", timeout=15)
    youtube.channels.return_value.list.assert_not_called()


def test_fetch_channel_seed_raises_when_handle_is_not_found():
    # Given
    youtube = _youtube_with_channels({"items": []})

    # When/Then
    with pytest.raises(ValidationError):
        fetch_channel_seed(youtube, "@missing", recent=10)


def test_fetch_channel_seed_raises_when_channel_has_no_uploads_playlist():
    # Given
    youtube = MagicMock()
    youtube.channels.return_value.list.return_value = _request(
        {
            "items": [
                {
                    "id": "UC_seed",
                    "snippet": {"title": "Seed Channel", "customUrl": "@seed"},
                    "statistics": {"subscriberCount": "1", "videoCount": "2"},
                    "contentDetails": {"relatedPlaylists": {}},
                }
            ]
        }
    )

    # When/Then
    with pytest.raises(ValidationError):
        fetch_channel_seed(youtube, "UC_seed", recent=10)


def test_fetch_channel_seed_wraps_channels_http_error():
    # Given
    youtube = MagicMock()
    error = _http_error(403)
    youtube.channels.return_value.list.return_value.execute.side_effect = error

    # When/Then
    with pytest.raises(YouTubeAPIError) as exc_info:
        fetch_channel_seed(youtube, "UC_seed", recent=10)
    assert exc_info.value.__cause__ is error
    assert exc_info.value.status_code == 403


def test_to_benchmark_entry_uses_domain_contract_shape():
    # Given
    seed = SeedChannel(
        channel_id="UC_seed",
        handle="@seed",
        name="Seed Channel",
        subscribers=12_345,
        total_videos=67,
        uploads_playlist_id="UU_seed",
        recent_titles=("First Video",),
    )

    # When
    entry = to_benchmark_entry(seed, relationship="seed")

    # Then
    assert entry == {
        "id": "UC_seed",
        "slug": "seed",
        "name": "Seed Channel",
        "relationship": "seed",
    }


def test_merge_benchmark_channel_appends_new_channel_without_mutating_input():
    # Given
    analytics = {"benchmark": {"channels": [{"id": "UC_existing", "slug": "existing"}]}}
    entry = {"id": "UC_seed", "slug": "seed", "name": "Seed Channel", "relationship": "seed"}

    # When
    merged = merge_benchmark_channel(analytics, entry)

    # Then
    assert merged["benchmark"]["channels"] == [
        {"id": "UC_existing", "slug": "existing"},
        {"id": "UC_seed", "slug": "seed", "name": "Seed Channel", "relationship": "seed"},
    ]
    assert analytics["benchmark"]["channels"] == [{"id": "UC_existing", "slug": "existing"}]


def test_merge_benchmark_channel_deduplicates_by_channel_id():
    # Given
    analytics = {
        "benchmark": {
            "channels": [
                {
                    "id": "UC_seed",
                    "slug": "old-seed",
                    "name": "Old Name",
                    "relationship": "seed",
                }
            ]
        }
    }
    entry = {"id": "UC_seed", "slug": "seed", "name": "Seed Channel", "relationship": "seed"}

    # When
    merged = merge_benchmark_channel(analytics, entry)

    # Then
    assert merged["benchmark"]["channels"] == [
        {
            "id": "UC_seed",
            "slug": "old-seed",
            "name": "Old Name",
            "relationship": "seed",
        }
    ]
