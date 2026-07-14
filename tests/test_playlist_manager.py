"""
PlaylistManager のユニットテスト

テスト対象: scripts/playlist_manager.py
YouTube API 呼び出しと load_config を unittest.mock でモック化して検証する。
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

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
    ):
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

    def test_activity_override_bypasses_title_resolver(self, manager, mock_config):
        """#80: activity を明示 override すると activity_for_theme は呼ばれない."""
        mock_config.content.title.activity_for_theme.reset_mock()
        mock_config.content.title.activity_for_theme.return_value = "Study"

        result = manager.resolve_playlists("village morning", activity="Gaming")

        mock_config.content.title.activity_for_theme.assert_not_called()
        assert "battle" in result  # Gaming が auto_add_activities に hit

    def test_activity_none_uses_title_resolver(self, manager, mock_config):
        """activity=None の場合は従来どおり activity_for_theme が呼ばれる."""
        mock_config.content.title.activity_for_theme.reset_mock()
        mock_config.content.title.activity_for_theme.return_value = "Gaming"

        manager.resolve_playlists("battle arena", activity=None)

        mock_config.content.title.activity_for_theme.assert_called_once_with("battle arena")


# ---------------------------------------------------------------------------
# create_all_playlists
# ---------------------------------------------------------------------------


class TestCreateAllPlaylists:
    def test_dry_run_no_api_calls(self, manager, capsys):
        """dry_run モードでは API コールが発生しない"""
        with patch.object(manager, "_create_playlist") as mock_create:
            result = manager.create_all_playlists(dry_run=True)
        assert result == {}
        mock_create.assert_not_called()

    def test_dry_run_prints_plan(self, manager, capsys):
        """dry_run モードで作成予定を表示する"""
        manager.create_all_playlists(dry_run=True)
        captured = capsys.readouterr()
        assert "DRY-RUN" in captured.out
        assert "New Playlist" in captured.out

    def test_skips_existing_playlists(self, manager):
        """playlist_id 既存のプレイリストはスキップする"""
        with (
            patch.object(
                manager,
                "_create_playlist",
                return_value={"status": "success", "playlist_id": "PL_NEW"},
            ),
            patch.object(manager, "_write_back_playlist_ids"),
        ):
            result = manager.create_all_playlists(dry_run=False)
        # new_playlist だけ作成される
        assert "new_playlist" in result
        assert len(result) == 1

    def test_create_success_writes_back(self, manager):
        """作成成功時に _write_back_playlist_ids が呼ばれる"""
        with (
            patch.object(
                manager,
                "_create_playlist",
                return_value={"status": "success", "playlist_id": "PL_CREATED"},
            ),
            patch.object(manager, "_write_back_playlist_ids") as mock_write,
        ):
            manager.create_all_playlists(dry_run=False)
            mock_write.assert_called_once()


# ---------------------------------------------------------------------------
# assign_video
# ---------------------------------------------------------------------------


class TestAssignVideo:
    def test_dry_run_no_api_calls(self, manager, capsys):
        """dry_run モードでは API コールが発生しない"""
        with patch.object(manager, "_add_video_to_playlist") as mock_add:
            result = manager.assign_video("VID123", "ocean waves", dry_run=True)
        # auto_add の 'all' と theme match の 'relaxation' がマッチ
        assert "all" in result
        mock_add.assert_not_called()

    def test_dry_run_prints_assignments(self, manager, capsys):
        """dry_run モードで割り当て予定を表示する"""
        manager.assign_video("VID123", "forest walk", dry_run=True)
        captured = capsys.readouterr()
        assert "DRY-RUN" in captured.out

    def test_skips_no_playlist_id(self, manager):
        """playlist_id 未設定のプレイリストはスキップする"""
        # new_playlist を auto_add にしてマッチさせる
        manager.config.playlists.items["new_playlist"]["auto_add"] = True
        with (
            patch.object(manager, "_list_playlist_video_ids", return_value=set()),
            patch.object(manager, "_add_video_to_playlist", return_value=True),
        ):
            result = manager.assign_video("VID1", "test", dry_run=False)
        # new_playlist は playlist_id 未設定なのでスキップ
        assert "new_playlist" not in result

    def test_collection_path_planning_activities_override(self, manager, mock_config, tmp_path):
        """#80: workflow-state.json の planning.activities が activity_for_theme を上書きする."""
        ws = tmp_path / "workflow-state.json"
        ws.write_text(json.dumps({"planning": {"activities": "Gaming"}}), encoding="utf-8")

        mock_config.content.title.activity_for_theme.reset_mock()
        mock_config.content.title.activity_for_theme.return_value = "Study"

        result = manager.assign_video("VID_X", "unknown-theme", dry_run=True, collection_path=tmp_path)

        mock_config.content.title.activity_for_theme.assert_not_called()
        assert "battle" in result

    def test_collection_path_without_planning_falls_back(self, manager, mock_config, tmp_path):
        """planning.activities が欠落していれば従来どおり activity_for_theme を使う."""
        ws = tmp_path / "workflow-state.json"
        ws.write_text(json.dumps({"theme": "ocean waves"}), encoding="utf-8")

        mock_config.content.title.activity_for_theme.reset_mock()
        mock_config.content.title.activity_for_theme.return_value = "Study"

        manager.assign_video("VID_X", "ocean waves", dry_run=True, collection_path=tmp_path)

        mock_config.content.title.activity_for_theme.assert_called_once_with("ocean waves")

    def test_collection_path_without_workflow_state_is_tolerated(self, manager, mock_config, tmp_path):
        """workflow-state.json が存在しなくても例外にならず、activity_for_theme に fallback."""
        mock_config.content.title.activity_for_theme.reset_mock()
        mock_config.content.title.activity_for_theme.return_value = "Study"

        # workflow-state.json は作らない
        manager.assign_video("VID_X", "ocean waves", dry_run=True, collection_path=tmp_path)

        mock_config.content.title.activity_for_theme.assert_called_once_with("ocean waves")

    def test_no_collection_path_uses_title_resolver(self, manager, mock_config):
        """collection_path 未指定なら従来どおりの経路（後方互換）."""
        mock_config.content.title.activity_for_theme.reset_mock()
        mock_config.content.title.activity_for_theme.return_value = "Study"

        manager.assign_video("VID_X", "ocean waves", dry_run=True)

        mock_config.content.title.activity_for_theme.assert_called_once_with("ocean waves")


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


# ---------------------------------------------------------------------------
# _create_playlist (旧 VideoUploader.create_playlist から PlaylistManager に内包)
# ---------------------------------------------------------------------------


class TestCreatePlaylist:
    def test_success(self, manager, mock_youtube):
        """プレイリスト作成成功時に playlist_id と URL を含む dict を返す"""
        mock_youtube.playlists.return_value.insert.return_value.execute.return_value = {"id": "PLabc123"}

        result = manager._create_playlist("My Playlist", "Desc")

        assert result["status"] == "success"
        assert result["playlist_id"] == "PLabc123"
        assert "PLabc123" in result["playlist_url"]
        assert result["title"] == "My Playlist"

    def test_failure(self, manager, mock_youtube):
        """API 例外時は status=failed と error メッセージを返す"""
        mock_youtube.playlists.return_value.insert.return_value.execute.side_effect = Exception("Quota exceeded")

        result = manager._create_playlist("Fail PL", "Desc")

        assert result["status"] == "failed"
        assert "Quota exceeded" in result["error"]
        assert result["title"] == "Fail PL"

    def test_passes_privacy_status(self, manager, mock_youtube):
        """privacy_status が body.status.privacyStatus に渡される"""
        mock_insert = mock_youtube.playlists.return_value.insert
        mock_insert.return_value.execute.return_value = {"id": "PL1"}

        manager._create_playlist("T", "D", privacy_status="unlisted")

        call_kwargs = mock_insert.call_args
        body = call_kwargs[1]["body"]
        assert body["status"]["privacyStatus"] == "unlisted"
        assert body["snippet"]["title"] == "T"

    def test_retries_transient_api_failure_through_playlist_manager(self, manager, mock_youtube, monkeypatch):
        monkeypatch.setattr("youtube_automation.utils.retry.time.sleep", lambda _: None)
        transient = HttpError(Response({"status": "503"}), b'{"error": {"errors": [{"reason": "backendError"}]}}')
        request = mock_youtube.playlists.return_value.insert.return_value
        request.execute.side_effect = [transient, {"id": "PL_NEW"}]

        result = manager._create_playlist("My Playlist", "Desc")

        assert result["playlist_id"] == "PL_NEW"
        assert request.execute.call_count == 2


# ---------------------------------------------------------------------------
# _add_video_to_playlist (旧 VideoUploader.add_video_to_playlist から内包)
# ---------------------------------------------------------------------------


class TestAddVideoToPlaylist:
    def test_success(self, manager, mock_youtube):
        """動画追加成功時に True を返す"""
        mock_youtube.playlistItems.return_value.insert.return_value.execute.return_value = {}

        result = manager._add_video_to_playlist("PL123", "VID456", position=0)

        assert result is True

    def test_failure(self, manager, mock_youtube):
        """API 例外時は False を返す"""
        mock_youtube.playlistItems.return_value.insert.return_value.execute.side_effect = Exception("API Error")

        result = manager._add_video_to_playlist("PL123", "VID456")

        assert result is False

    def test_passes_correct_body(self, manager, mock_youtube):
        """playlistId / resourceId / position が body に渡される"""
        mock_insert = mock_youtube.playlistItems.return_value.insert
        mock_insert.return_value.execute.return_value = {}

        manager._add_video_to_playlist("PL_ABC", "VID_XYZ", position=3)

        call_kwargs = mock_insert.call_args
        assert call_kwargs[1]["part"] == "snippet"
        body = call_kwargs[1]["body"]
        assert body["snippet"]["playlistId"] == "PL_ABC"
        assert body["snippet"]["resourceId"]["videoId"] == "VID_XYZ"
        assert body["snippet"]["position"] == 3

    def test_position_none_omits_position_key(self, manager, mock_youtube):
        """position=None 指定時は body.snippet に position キーが含まれない（末尾追加を API に委ねる）"""
        mock_insert = mock_youtube.playlistItems.return_value.insert
        mock_insert.return_value.execute.return_value = {}

        result = manager._add_video_to_playlist("PL_END", "VID_TAIL", position=None)

        assert result is True
        call_kwargs = mock_insert.call_args
        body = call_kwargs[1]["body"]
        assert body["snippet"]["playlistId"] == "PL_END"
        assert body["snippet"]["resourceId"]["videoId"] == "VID_TAIL"
        assert "position" not in body["snippet"]

    def test_position_zero_includes_position_key(self, manager, mock_youtube):
        """position=0 は明示的に先頭挿入として body に含まれる（falsy 0 を None と誤判定しない）"""
        mock_insert = mock_youtube.playlistItems.return_value.insert
        mock_insert.return_value.execute.return_value = {}

        manager._add_video_to_playlist("PL_HEAD", "VID_FIRST", position=0)

        body = mock_insert.call_args[1]["body"]
        assert body["snippet"]["position"] == 0


PLAYLIST_ID_STRING_SHAPE = "PL_test_string_275"


def _string_shape_channel(tmp_path: Path) -> Path:
    ch = tmp_path / "channel"
    cdir = ch / "config" / "channel"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "meta.json").write_text(
        json.dumps(
            {
                "channel": {
                    "name": "Test Channel",
                    "short": "TC",
                    "youtube_handle": "@testchannel",
                    "url": "https://youtube.com/@testchannel",
                    "tagline": "Test tagline",
                }
            }
        ),
        encoding="utf-8",
    )
    (cdir / "content.json").write_text(
        json.dumps(
            {
                "genre": {"primary": "chiptune", "style": "8-bit", "context": "RPG"},
                "tags": {"base": ["chiptune"], "themes": {}},
                "descriptions": {
                    "opening": "{style} {primary} for {context}",
                    "perfect_for": ["Study"],
                    "hashtags": [],
                },
                "title": {"template": "{theme}", "default_activity": "Study"},
            }
        ),
        encoding="utf-8",
    )
    (cdir / "youtube.json").write_text(
        json.dumps(
            {
                "youtube": {
                    "category_id": "10",
                    "privacy_status": "public",
                    "language": "ja",
                }
            }
        ),
        encoding="utf-8",
    )
    (cdir / "playlists.json").write_text(
        json.dumps({"playlists": {"main": PLAYLIST_ID_STRING_SHAPE}}),
        encoding="utf-8",
    )
    return ch


import youtube_automation.scripts.playlist_manager as _playlist_manager_module  # noqa: E402


class TestStringShapePlaylistsRegression:
    def test_resolve_playlists_does_not_raise_on_string_shape(self, tmp_path, monkeypatch):
        ch = _string_shape_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        with patch.object(_playlist_manager_module, "get_youtube", return_value=MagicMock()):
            manager = _playlist_manager_module.PlaylistManager()
            result = manager.resolve_playlists("any-theme")

        assert result == ["main"]

    def test_assign_video_dry_run_does_not_raise_on_string_shape(self, tmp_path, monkeypatch):
        ch = _string_shape_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        with patch.object(_playlist_manager_module, "get_youtube", return_value=MagicMock()):
            manager = _playlist_manager_module.PlaylistManager()
            assigned = manager.assign_video("VID_X", "any-theme", dry_run=True)

        assert assigned == ["main"]

    def test_create_all_playlists_dry_run_skips_string_shape(self, tmp_path, monkeypatch):
        ch = _string_shape_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        with patch.object(_playlist_manager_module, "get_youtube", return_value=MagicMock()):
            manager = _playlist_manager_module.PlaylistManager()
            created = manager.create_all_playlists(dry_run=True)

        assert created == {}

    def test_clean_deleted_entries_dry_run_does_not_raise_on_string_shape(self, tmp_path, monkeypatch):
        ch = _string_shape_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        mock_youtube = MagicMock()
        mock_youtube.playlistItems.return_value.list.return_value.execute.return_value = {"items": []}

        with patch.object(_playlist_manager_module, "get_youtube", return_value=mock_youtube):
            manager = _playlist_manager_module.PlaylistManager()
            result = manager.clean_deleted_entries(dry_run=True)

        assert result == {"main": 0}
