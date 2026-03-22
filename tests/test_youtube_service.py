"""
youtube_service モジュールのユニットテスト

テスト対象: utils/youtube_service.py
シングルトンキャッシュ動作を unittest.mock で検証する。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import utils.youtube_service as yt_service

# ---------------------------------------------------------------------------
# フィクスチャ: 各テストでキャッシュをリセット
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_service():
    """各テスト前後にシングルトンキャッシュをリセット"""
    yt_service.reset()
    yield
    yt_service.reset()


# ---------------------------------------------------------------------------
# get_youtube
# ---------------------------------------------------------------------------

class TestGetYoutube:
    @patch('utils.youtube_service._get_handler')
    def test_returns_youtube_service(self, mock_get_handler):
        mock_handler = MagicMock()
        mock_handler.get_youtube_service.return_value = "fake_youtube_service"
        mock_get_handler.return_value = mock_handler

        result = yt_service.get_youtube()
        assert result == "fake_youtube_service"
        mock_handler.get_youtube_service.assert_called_once()

    @patch('utils.youtube_service._get_handler')
    def test_caches_service(self, mock_get_handler):
        mock_handler = MagicMock()
        mock_handler.get_youtube_service.return_value = "fake_youtube_service"
        mock_get_handler.return_value = mock_handler

        first = yt_service.get_youtube()
        second = yt_service.get_youtube()

        assert first is second
        # handler.get_youtube_service called only once due to caching
        mock_handler.get_youtube_service.assert_called_once()


# ---------------------------------------------------------------------------
# get_analytics
# ---------------------------------------------------------------------------

class TestGetAnalytics:
    @patch('utils.youtube_service.build')
    @patch('utils.youtube_service._get_handler')
    def test_returns_analytics_service(self, mock_get_handler, mock_build):
        mock_handler = MagicMock()
        mock_creds = MagicMock()
        mock_handler.authenticate.return_value = mock_creds
        mock_get_handler.return_value = mock_handler
        mock_build.return_value = "fake_analytics_service"

        result = yt_service.get_analytics()

        assert result == "fake_analytics_service"
        mock_build.assert_called_once_with('youtubeAnalytics', 'v2', credentials=mock_creds)

    @patch('utils.youtube_service.build')
    @patch('utils.youtube_service._get_handler')
    def test_caches_service(self, mock_get_handler, mock_build):
        mock_handler = MagicMock()
        mock_handler.authenticate.return_value = MagicMock()
        mock_get_handler.return_value = mock_handler
        mock_build.return_value = "fake_analytics_service"

        first = yt_service.get_analytics()
        second = yt_service.get_analytics()

        assert first is second
        mock_build.assert_called_once()


# ---------------------------------------------------------------------------
# get_credentials
# ---------------------------------------------------------------------------

class TestGetCredentials:
    @patch('utils.youtube_service._get_handler')
    def test_returns_credentials(self, mock_get_handler):
        mock_handler = MagicMock()
        mock_creds = MagicMock()
        mock_handler.authenticate.return_value = mock_creds
        mock_get_handler.return_value = mock_handler

        result = yt_service.get_credentials()
        assert result is mock_creds


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

class TestReset:
    @patch('utils.youtube_service._get_handler')
    def test_reset_clears_cache(self, mock_get_handler):
        mock_handler = MagicMock()
        mock_handler.get_youtube_service.side_effect = ["service_1", "service_2"]
        mock_get_handler.return_value = mock_handler

        first = yt_service.get_youtube()
        assert first == "service_1"

        yt_service.reset()

        second = yt_service.get_youtube()
        assert second == "service_2"
        assert first != second
        assert mock_handler.get_youtube_service.call_count == 2
