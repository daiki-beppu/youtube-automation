"""重複検索 helper の単体契約。"""

from unittest.mock import MagicMock

from youtube_automation.domains.uploads.youtube import DedupSearch


def test_search_helper_uses_injected_youtube_service() -> None:
    youtube = MagicMock()
    youtube.search.return_value.list.return_value.execute.return_value = {"items": []}

    assert DedupSearch(youtube).find_existing_video_by_title("Rainy Jazz") is None

    youtube.search.return_value.list.assert_called_once_with(
        forMine=True,
        type="video",
        q="Rainy Jazz",
        maxResults=10,
        part="snippet",
    )
