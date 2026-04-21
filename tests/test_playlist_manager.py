"""
PlaylistManager のユニットテスト

テスト対象: scripts/playlist_manager.py
YouTube API 呼び出しと load_config を unittest.mock でモック化して検証する。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------


SAMPLE_PLAYLISTS_CONFIG = {
    "all": {
        "title": "All Videos",
        "auto_add": True,
        "playlist_id": "PL_ALL",
    },
    "battle": {
        "title": "Battle Music",
        "auto_add_activities": ["Gaming"],
        "playlist_id": "PL_BATTLE",
    },
    "relaxation": {
        "title": "Relaxation Music",
        "auto_add_themes": ["ocean", "forest"],
        "playlist_id": "PL_RELAX",
    },
    "new_playlist": {
        "title": "New Playlist",
        "description": "A brand new playlist",
        # playlist_id 未設定
    },
}


@pytest.fixture
def mock_config():
    """ChannelConfig (新 API) のモック"""
    config = MagicMock()
    config.meta.channel_name = "Test Channel"
    config.meta.channel_short = "TC"
    config.playlists.items = SAMPLE_PLAYLISTS_CONFIG
    config.content.title.activity_for_theme = MagicMock(return_value="Study")
    return config


@pytest.fixture
def mock_youtube():
    """モック化された YouTube API サービス"""
    return MagicMock()


@pytest.fixture
def manager(mock_config, mock_youtube):
    """PlaylistManager インスタンスを返す（外部依存をモック）"""
    with (
        patch("youtube_automation.scripts.playlist_manager.load_config", return_value=mock_config),
        patch("youtube_automation.scripts.playlist_manager.channel_dir", return_value=Path("/tmp/fake_channel")),
        patch("youtube_automation.scripts.playlist_manager.get_youtube", return_value=mock_youtube),
        patch("youtube_automation.scripts.playlist_manager.VideoUploader") as MockUploader,
    ):
        mock_uploader_instance = MagicMock()
        MockUploader.return_value = mock_uploader_instance

        from youtube_automation.scripts.playlist_manager import PlaylistManager

        obj = PlaylistManager()
        obj._youtube = mock_youtube
        yield obj


# ---------------------------------------------------------------------------
# resolve_playlists
# ---------------------------------------------------------------------------


class TestResolvePlaylists:
    def test_auto_add_always_matched(self, manager):
        """auto_add=True のプレイリストは常にマッチする"""
        result = manager.resolve_playlists("anything")
        assert "all" in result

    def test_activity_matching(self, manager, mock_config):
        """activity ベースのマッチング"""
        mock_config.content.title.activity_for_theme.return_value = "Gaming"
        result = manager.resolve_playlists("battle arena")
        assert "battle" in result

    def test_theme_keyword_matching(self, manager):
        """theme キーワードベースのマッチング"""
        result = manager.resolve_playlists("Deep Ocean Waves")
        assert "relaxation" in result

    def test_theme_keyword_case_insensitive(self, manager):
        """テーマキーワードは大文字小文字を区別しない"""
        result = manager.resolve_playlists("FOREST Ambience")
        assert "relaxation" in result

    def test_no_match_beyond_auto_add(self, manager):
        """auto_add 以外にマッチしない場合"""
        mock_config = manager.config
        mock_config.content.title.activity_for_theme.return_value = "Study"
        result = manager.resolve_playlists("village morning")
        # 'all' は auto_add で常にマッチ、他はマッチしない
        assert result == ["all"]


# ---------------------------------------------------------------------------
# create_all_playlists
# ---------------------------------------------------------------------------


class TestCreateAllPlaylists:
    def test_dry_run_no_api_calls(self, manager, capsys):
        """dry_run モードでは API コールが発生しない"""
        result = manager.create_all_playlists(dry_run=True)
        assert result == {}
        # uploader.create_playlist が呼ばれていないことを確認
        manager.uploader.create_playlist.assert_not_called()

    def test_dry_run_prints_plan(self, manager, capsys):
        """dry_run モードで作成予定を表示する"""
        manager.create_all_playlists(dry_run=True)
        captured = capsys.readouterr()
        assert "DRY-RUN" in captured.out
        assert "New Playlist" in captured.out

    def test_skips_existing_playlists(self, manager):
        """playlist_id 既存のプレイリストはスキップする"""
        manager.uploader.create_playlist.return_value = {
            "status": "success",
            "playlist_id": "PL_NEW",
        }
        with patch.object(manager, "_write_back_playlist_ids"):
            result = manager.create_all_playlists(dry_run=False)
        # new_playlist だけ作成される
        assert "new_playlist" in result
        assert len(result) == 1

    def test_create_success_writes_back(self, manager):
        """作成成功時に _write_back_playlist_ids が呼ばれる"""
        manager.uploader.create_playlist.return_value = {
            "status": "success",
            "playlist_id": "PL_CREATED",
        }
        with patch.object(manager, "_write_back_playlist_ids") as mock_write:
            manager.create_all_playlists(dry_run=False)
            mock_write.assert_called_once()


# ---------------------------------------------------------------------------
# assign_video
# ---------------------------------------------------------------------------


class TestAssignVideo:
    def test_dry_run_no_api_calls(self, manager, capsys):
        """dry_run モードでは API コールが発生しない"""
        result = manager.assign_video("VID123", "ocean waves", dry_run=True)
        # auto_add の 'all' と theme match の 'relaxation' がマッチ
        assert "all" in result
        manager.uploader.add_video_to_playlist.assert_not_called()

    def test_dry_run_prints_assignments(self, manager, capsys):
        """dry_run モードで割り当て予定を表示する"""
        manager.assign_video("VID123", "forest walk", dry_run=True)
        captured = capsys.readouterr()
        assert "DRY-RUN" in captured.out

    def test_skips_no_playlist_id(self, manager):
        """playlist_id 未設定のプレイリストはスキップする"""
        # new_playlist を auto_add にしてマッチさせる
        manager.config.playlists.items["new_playlist"]["auto_add"] = True
        with patch.object(manager, "_list_playlist_video_ids", return_value=set()):
            manager.uploader.add_video_to_playlist.return_value = True
            result = manager.assign_video("VID1", "test", dry_run=False)
        # new_playlist は playlist_id 未設定なのでスキップ
        assert "new_playlist" not in result


# ---------------------------------------------------------------------------
# _list_playlist_video_ids
# ---------------------------------------------------------------------------


class TestListPlaylistVideoIds:
    def test_success(self, manager, mock_youtube):
        """プレイリスト内の動画 ID セットを返す"""
        mock_response = {
            "items": [
                {"contentDetails": {"videoId": "VID_A"}},
                {"contentDetails": {"videoId": "VID_B"}},
            ],
        }
        mock_list = mock_youtube.playlistItems.return_value.list
        mock_list.return_value.execute.return_value = mock_response
        # list_next で None を返してページネーション終了
        mock_youtube.playlistItems.return_value.list_next.return_value = None

        result = manager._list_playlist_video_ids("PL_TEST")
        assert result == {"VID_A", "VID_B"}

    def test_empty_playlist(self, manager, mock_youtube):
        """空のプレイリストでは空セットを返す"""
        mock_response = {"items": []}
        mock_list = mock_youtube.playlistItems.return_value.list
        mock_list.return_value.execute.return_value = mock_response
        mock_youtube.playlistItems.return_value.list_next.return_value = None

        result = manager._list_playlist_video_ids("PL_EMPTY")
        assert result == set()

    def test_api_error_returns_empty(self, manager, mock_youtube):
        """API エラー時は空セットを返す"""
        mock_youtube.playlistItems.return_value.list.return_value.execute.side_effect = Exception("API Error")

        result = manager._list_playlist_video_ids("PL_FAIL")
        assert result == set()
