"""
VideoUploader のユニットテスト

テスト対象: scripts/video_uploader.py
YouTube API 呼び出しを unittest.mock でモック化して検証する。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_youtube():
    """モック化された YouTube API サービスオブジェクト"""
    return MagicMock()


@pytest.fixture
def uploader(mock_youtube):
    """VideoUploader インスタンスを返す（YouTubeUploadCore.initialize をモック）"""
    with patch("youtube_automation.utils.upload_core.get_youtube", return_value=mock_youtube):
        from youtube_automation.scripts.video_uploader import VideoUploader

        obj = VideoUploader()
        obj.youtube = mock_youtube
        yield obj


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    @patch("youtube_automation.utils.upload_core.get_youtube", return_value=MagicMock())
    def test_init_calls_super(self, _mock_get_yt):
        """__init__ が YouTubeUploadCore.__init__() を呼ぶ"""
        from youtube_automation.scripts.video_uploader import VideoUploader

        obj = VideoUploader(auth_dir="/tmp/fake")
        assert obj.youtube is None  # super().__init__() で None 初期化

    @patch("youtube_automation.utils.upload_core.get_youtube", return_value=MagicMock())
    def test_init_without_args(self, _mock_get_yt):
        """auth_dir 省略でもインスタンス化できる"""
        from youtube_automation.scripts.video_uploader import VideoUploader

        obj = VideoUploader()
        assert obj.youtube is None


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------


class TestAuthenticate:
    def test_authenticate_calls_initialize(self, uploader):
        """authenticate() が self.initialize() を呼ぶ"""
        with patch.object(uploader, "initialize") as mock_init:
            uploader.authenticate()
            mock_init.assert_called_once()


# ---------------------------------------------------------------------------
# upload_video
# ---------------------------------------------------------------------------


class TestUploadVideo:
    @patch("os.path.getsize", return_value=1024 * 1024 * 10)
    def test_upload_video_success(self, _mock_size, uploader):
        """アップロード成功時に video_id と URL を含む dict を返す"""
        with patch("youtube_automation.utils.upload_core.YouTubeUploadCore.upload_video", return_value="abc123"):
            result = uploader.upload_video(
                video_file="/tmp/test.mp4",
                title="Test Video",
                description="Test Description",
                tags=["tag1", "tag2"],
            )
        assert result["status"] == "success"
        assert result["video_id"] == "abc123"
        assert result["video_url"] == "https://youtu.be/abc123"
        assert result["title"] == "Test Video"

    @patch("os.path.getsize", return_value=1024 * 1024 * 10)
    def test_upload_video_failure(self, _mock_size, uploader):
        """アップロード失敗時に status=failed を返す"""
        with patch("youtube_automation.utils.upload_core.YouTubeUploadCore.upload_video", return_value=None):
            result = uploader.upload_video(
                video_file="/tmp/test.mp4",
                title="Fail Video",
                description="Desc",
                tags=[],
            )
        assert result["status"] == "failed"
        assert result["title"] == "Fail Video"

    @patch("os.path.getsize", return_value=1024 * 1024 * 5)
    def test_upload_video_passes_body_to_core(self, _mock_size, uploader):
        """upload_video が正しい body を YouTubeUploadCore.upload_video に渡す"""
        target = "youtube_automation.utils.upload_core.YouTubeUploadCore.upload_video"
        with patch(target, return_value="xyz") as mock_core:
            uploader.upload_video(
                video_file="/tmp/test.mp4",
                title="T",
                description="D",
                tags=["t"],
                category_id="20",
                privacy_status="private",
            )
            call_args = mock_core.call_args
            body = call_args[0][1]
            assert body["snippet"]["title"] == "T"
            assert body["snippet"]["categoryId"] == "20"
            assert body["status"]["privacyStatus"] == "private"


# ---------------------------------------------------------------------------
# create_playlist
# ---------------------------------------------------------------------------


class TestCreatePlaylist:
    def test_create_playlist_success(self, uploader, mock_youtube):
        """プレイリスト作成成功時に playlist_id と URL を返す"""
        mock_youtube.playlists.return_value.insert.return_value.execute.return_value = {
            "id": "PLabc123",
        }
        result = uploader.create_playlist(title="My Playlist", description="Desc")
        assert result["status"] == "success"
        assert result["playlist_id"] == "PLabc123"
        assert "PLabc123" in result["playlist_url"]

    def test_create_playlist_failure(self, uploader, mock_youtube):
        """プレイリスト作成失敗時に status=failed を返す"""
        mock_youtube.playlists.return_value.insert.return_value.execute.side_effect = Exception("API Error")
        result = uploader.create_playlist(title="Fail PL", description="Desc")
        assert result["status"] == "failed"
        assert "API Error" in result["error"]

    def test_create_playlist_auto_authenticates(self, mock_youtube):
        """youtube が None なら authenticate() が呼ばれる"""
        with patch("youtube_automation.utils.upload_core.get_youtube", return_value=mock_youtube):
            from youtube_automation.scripts.video_uploader import VideoUploader

            obj = VideoUploader()
            assert obj.youtube is None
            with patch.object(obj, "authenticate") as mock_auth:
                mock_youtube.playlists.return_value.insert.return_value.execute.return_value = {"id": "PL1"}
                obj.create_playlist("T", "D")
                mock_auth.assert_called_once()


# ---------------------------------------------------------------------------
# add_video_to_playlist
# ---------------------------------------------------------------------------


class TestAddVideoToPlaylist:
    def test_add_video_success(self, uploader, mock_youtube):
        """動画のプレイリスト追加成功時に True を返す"""
        mock_youtube.playlistItems.return_value.insert.return_value.execute.return_value = {}
        result = uploader.add_video_to_playlist("PL123", "VID456", position=0)
        assert result is True

    def test_add_video_failure(self, uploader, mock_youtube):
        """動画のプレイリスト追加失敗時に False を返す"""
        mock_youtube.playlistItems.return_value.insert.return_value.execute.side_effect = Exception("Quota exceeded")
        result = uploader.add_video_to_playlist("PL123", "VID456")
        assert result is False

    def test_add_video_passes_correct_body(self, uploader, mock_youtube):
        """add_video_to_playlist が正しいリクエストボディを送信する"""
        mock_insert = mock_youtube.playlistItems.return_value.insert
        mock_insert.return_value.execute.return_value = {}
        uploader.add_video_to_playlist("PL_ABC", "VID_XYZ", position=3)
        call_kwargs = mock_insert.call_args
        assert call_kwargs[1]["part"] == "snippet"

    def test_add_video_auto_authenticates(self, mock_youtube):
        """youtube が None なら authenticate() が呼ばれる"""
        with patch("youtube_automation.utils.upload_core.get_youtube", return_value=mock_youtube):
            from youtube_automation.scripts.video_uploader import VideoUploader

            obj = VideoUploader()
            assert obj.youtube is None
            with patch.object(obj, "authenticate") as mock_auth:
                mock_youtube.playlistItems.return_value.insert.return_value.execute.return_value = {}
                obj.add_video_to_playlist("PL1", "V1")
                mock_auth.assert_called_once()
