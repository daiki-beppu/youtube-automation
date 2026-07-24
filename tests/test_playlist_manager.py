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

from youtube_automation.infrastructure.errors import ValidationError
from youtube_automation.infrastructure.google.youtube import YouTubeClients

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
    import youtube_automation.domains.uploads.playlists as playlist_domain

    handler = MagicMock()
    handler.get_youtube_service.return_value = mock_youtube
    clients = YouTubeClients(full_handler=handler)
    with (
        patch.object(playlist_domain, "load_config", return_value=mock_config),
        patch.object(playlist_domain, "channel_dir", return_value=Path("/tmp/fake_channel")),
    ):
        obj = playlist_domain.PlaylistManager(clients=clients)
        obj._youtube = mock_youtube
        yield obj


@pytest.fixture
def quota_log():
    with patch("youtube_automation.infrastructure.quota.log_quota") as mock_log:
        yield mock_log


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
        mock_youtube.playlistItems.return_value.list.return_value.execute.side_effect = OSError("API Error")

        result = manager._list_playlist_video_ids("PL_FAIL")
        assert result == set()

    def test_retries_transient_api_failure(self, manager, mock_youtube, monkeypatch, quota_log):
        monkeypatch.setattr("youtube_automation.infrastructure.retry.time.sleep", lambda _: None)
        request = mock_youtube.playlistItems.return_value.list.return_value
        request.execute.side_effect = [
            HttpError(Response({"status": "503"}), b'{"error": {"errors": [{"reason": "backendError"}]}}'),
            {"items": [{"contentDetails": {"videoId": "VID_RETRY"}}]},
        ]
        mock_youtube.playlistItems.return_value.list_next.return_value = None

        assert manager._list_playlist_video_ids("PL_RETRY") == {"VID_RETRY"}
        assert request.execute.call_count == 2
        assert quota_log.call_count == 2


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
        mock_youtube.playlists.return_value.insert.return_value.execute.side_effect = OSError("Quota exceeded")

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

    def test_retries_transient_api_failure_through_playlist_manager(
        self, manager, mock_youtube, monkeypatch, quota_log
    ):
        monkeypatch.setattr("youtube_automation.infrastructure.retry.time.sleep", lambda _: None)
        transient = HttpError(Response({"status": "503"}), b'{"error": {"errors": [{"reason": "backendError"}]}}')
        request = mock_youtube.playlists.return_value.insert.return_value
        request.execute.side_effect = [transient, {"id": "PL_NEW"}]

        result = manager._create_playlist("My Playlist", "Desc")

        assert result["playlist_id"] == "PL_NEW"
        assert request.execute.call_count == 2
        assert quota_log.call_count == 2


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
        mock_youtube.playlistItems.return_value.insert.return_value.execute.side_effect = OSError("API Error")

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

    def test_retries_transient_api_failure(self, manager, mock_youtube, monkeypatch, quota_log):
        monkeypatch.setattr("youtube_automation.infrastructure.retry.time.sleep", lambda _: None)
        request = mock_youtube.playlistItems.return_value.insert.return_value
        request.execute.side_effect = [
            HttpError(Response({"status": "503"}), b'{"error": {"errors": [{"reason": "backendError"}]}}'),
            {},
        ]

        assert manager._add_video_to_playlist("PL_RETRY", "VID_RETRY") is True
        assert request.execute.call_count == 2
        assert quota_log.call_count == 2


# ---------------------------------------------------------------------------
# quota 記録（#2059: mutation 経路の log_quota 配線）
# ---------------------------------------------------------------------------


class TestQuotaLogging:
    @pytest.fixture
    def quota_log(self):
        """playlist_manager 名前空間の log_quota をモック化して記録を検証する"""
        with patch("youtube_automation.infrastructure.quota.log_quota") as mock_log:
            yield mock_log

    def test_create_playlist_records_playlists_insert_once(self, manager, mock_youtube, quota_log):
        """playlist create で playlists.insert (50 units) が 1 回記録される"""
        mock_youtube.playlists.return_value.insert.return_value.execute.return_value = {"id": "PL_Q1"}

        manager._create_playlist("Quota Playlist", "Desc")

        quota_log.assert_called_once()
        args, kwargs = quota_log.call_args
        assert args == ("youtube-data-api", "playlists.insert", 50)
        assert kwargs["metadata"] == {"title": "Quota Playlist"}

    def test_add_video_records_playlist_items_insert_per_request(self, manager, mock_youtube, quota_log):
        """item add で playlistItems.insert (50 units) が request 数だけ記録される"""
        mock_youtube.playlistItems.return_value.insert.return_value.execute.return_value = {}

        manager._add_video_to_playlist("PL_Q", "VID_1", position=0)
        manager._add_video_to_playlist("PL_Q", "VID_2", position=0)

        insert_calls = [c for c in quota_log.call_args_list if c.args[1] == "playlistItems.insert"]
        assert len(insert_calls) == 2
        for call in insert_calls:
            assert call.args == ("youtube-data-api", "playlistItems.insert", 50)
        assert insert_calls[0].kwargs["metadata"] == {"playlist_id": "PL_Q", "video_id": "VID_1"}

    def test_list_playlist_video_ids_records_list_per_page(self, manager, mock_youtube, quota_log):
        """read-before-write の playlistItems.list (1 unit) がページ単位で記録される"""
        page1 = {"items": [{"contentDetails": {"videoId": "VID_A"}}]}
        page2 = {"items": [{"contentDetails": {"videoId": "VID_B"}}]}
        mock_items = mock_youtube.playlistItems.return_value
        mock_items.list.return_value.execute.return_value = page1
        next_request = MagicMock()
        next_request.execute.return_value = page2
        mock_items.list_next.side_effect = [next_request, None]

        result = manager._list_playlist_video_ids("PL_PAGED")

        assert result == {"VID_A", "VID_B"}
        list_calls = [c for c in quota_log.call_args_list if c.args[1] == "playlistItems.list"]
        assert len(list_calls) == 2
        for call in list_calls:
            assert call.args == ("youtube-data-api", "playlistItems.list", 1)

    def test_clean_deleted_entries_records_list_and_delete_separately(self, manager, mock_youtube, quota_log):
        """cleanup で playlistItems.list と playlistItems.delete が別 operation で記録される"""
        mock_items = mock_youtube.playlistItems.return_value
        mock_items.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "ITEM_DEL",
                    "snippet": {"title": "Deleted video", "resourceId": {"videoId": "VID_GONE"}},
                },
                {
                    "id": "ITEM_OK",
                    "snippet": {"title": "Alive video", "resourceId": {"videoId": "VID_OK"}},
                },
            ]
        }
        mock_items.delete.return_value.execute.return_value = ""

        manager.clean_deleted_entries(dry_run=False)

        buckets = [c.args[1] for c in quota_log.call_args_list]
        # playlist_id 設定済みの 3 プレイリスト分の list + delete 1 件 × 3
        assert buckets.count("playlistItems.list") == 3
        assert buckets.count("playlistItems.delete") == 3
        delete_calls = [c for c in quota_log.call_args_list if c.args[1] == "playlistItems.delete"]
        assert delete_calls[0].args == ("youtube-data-api", "playlistItems.delete", 50)
        assert delete_calls[0].kwargs["metadata"]["video_id"] == "VID_GONE"

    def test_clean_list_retries_transient_api_failure(self, manager, mock_youtube, monkeypatch, quota_log):
        monkeypatch.setattr("youtube_automation.infrastructure.retry.time.sleep", lambda _: None)
        manager.config.playlists.items = {"main": {"playlist_id": "PL_RETRY"}}
        request = mock_youtube.playlistItems.return_value.list.return_value
        request.execute.side_effect = [
            HttpError(Response({"status": "503"}), b'{"error": {"errors": [{"reason": "backendError"}]}}'),
            {"items": []},
        ]

        assert manager.clean_deleted_entries() == {"main": 0}
        assert request.execute.call_count == 2
        assert quota_log.call_count == 2

    def test_clean_delete_retries_transient_api_failure(self, manager, mock_youtube, monkeypatch, quota_log):
        monkeypatch.setattr("youtube_automation.infrastructure.retry.time.sleep", lambda _: None)
        manager.config.playlists.items = {"main": {"playlist_id": "PL_RETRY"}}
        mock_items = mock_youtube.playlistItems.return_value
        mock_items.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "ITEM_DEL",
                    "snippet": {"title": "Deleted video", "resourceId": {"videoId": "VID_GONE"}},
                }
            ]
        }
        delete_request = mock_items.delete.return_value
        delete_request.execute.side_effect = [
            HttpError(Response({"status": "503"}), b'{"error": {"errors": [{"reason": "backendError"}]}}'),
            "",
        ]

        assert manager.clean_deleted_entries() == {"main": 1}
        assert delete_request.execute.call_count == 2
        assert quota_log.call_count == 3

    def test_clean_deleted_entries_dry_run_records_list_only(self, manager, mock_youtube, quota_log):
        """dry-run では list のみ記録され delete は記録されない"""
        mock_items = mock_youtube.playlistItems.return_value
        mock_items.list.return_value.execute.return_value = {
            "items": [
                {
                    "id": "ITEM_DEL",
                    "snippet": {"title": "Deleted video", "resourceId": {"videoId": "VID_GONE"}},
                },
            ]
        }

        manager.clean_deleted_entries(dry_run=True)

        buckets = [c.args[1] for c in quota_log.call_args_list]
        assert buckets.count("playlistItems.list") == 3
        assert buckets.count("playlistItems.delete") == 0

    @pytest.mark.parametrize("response", [None, {"items": None}, {"items": {}}, {"items": [None]}])
    def test_clean_deleted_entries_rejects_invalid_response_shape(self, manager, response):
        manager.config.playlists.items = {"main": {"playlist_id": "PL_MAIN"}}
        manager._youtube.playlistItems.return_value.list.return_value.execute.return_value = response

        with pytest.raises(ValidationError):
            manager.clean_deleted_entries()

    def test_create_playlist_failure_still_records_quota_and_keeps_error(self, manager, mock_youtube, quota_log):
        """create 失敗時も quota が記録され、元のエラーハンドリング（failed dict）が維持される"""
        mock_youtube.playlists.return_value.insert.return_value.execute.side_effect = OSError("Quota exceeded")

        result = manager._create_playlist("Fail PL", "Desc")

        assert result["status"] == "failed"
        assert "Quota exceeded" in result["error"]
        assert quota_log.call_count == 3
        assert quota_log.call_args.args == ("youtube-data-api", "playlists.insert", 50)

    def test_add_video_failure_still_records_quota_and_keeps_error(self, manager, mock_youtube, quota_log):
        """add 失敗時も quota が記録され、元のエラーハンドリング（False 返却）が維持される"""
        mock_youtube.playlistItems.return_value.insert.return_value.execute.side_effect = OSError("API Error")

        result = manager._add_video_to_playlist("PL_F", "VID_F")

        assert result is False
        assert quota_log.call_count == 3
        assert quota_log.call_args.args == ("youtube-data-api", "playlistItems.insert", 50)


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


import youtube_automation.domains.uploads.playlists as _playlist_manager_module  # noqa: E402


class TestStringShapePlaylistsRegression:
    def test_resolve_playlists_does_not_raise_on_string_shape(self, tmp_path, monkeypatch):
        ch = _string_shape_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        clients = YouTubeClients(full_handler=MagicMock())
        manager = _playlist_manager_module.PlaylistManager(clients=clients)
        result = manager.resolve_playlists("any-theme")

        assert result == ["main"]

    def test_assign_video_dry_run_does_not_raise_on_string_shape(self, tmp_path, monkeypatch):
        ch = _string_shape_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        manager = _playlist_manager_module.PlaylistManager(clients=YouTubeClients(full_handler=MagicMock()))
        assigned = manager.assign_video("VID_X", "any-theme", dry_run=True)

        assert assigned == ["main"]

    def test_create_all_playlists_dry_run_skips_string_shape(self, tmp_path, monkeypatch):
        ch = _string_shape_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        manager = _playlist_manager_module.PlaylistManager(clients=YouTubeClients(full_handler=MagicMock()))
        created = manager.create_all_playlists(dry_run=True)

        assert created == {}

    def test_clean_deleted_entries_dry_run_does_not_raise_on_string_shape(self, tmp_path, monkeypatch):
        ch = _string_shape_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        mock_youtube = MagicMock()
        mock_youtube.playlistItems.return_value.list.return_value.execute.return_value = {"items": []}

        handler = MagicMock()
        handler.get_youtube_service.return_value = mock_youtube
        manager = _playlist_manager_module.PlaylistManager(clients=YouTubeClients(full_handler=handler))
        result = manager.clean_deleted_entries(dry_run=True)

        assert result == {"main": 0}


def test_create_playlist_returns_failure_for_invalid_api_response(manager):
    manager._youtube.playlists.return_value.insert.return_value.execute.return_value = {}

    result = manager._create_playlist("New", "Description")

    assert result == {"status": "failed", "error": "playlists.insert response is missing id", "title": "New"}


def test_list_playlist_video_ids_returns_partial_result_for_invalid_item(manager):
    request = manager._youtube.playlistItems.return_value.list.return_value
    request.execute.return_value = {"items": [{"contentDetails": {"videoId": "v1"}}, {"contentDetails": {}}]}

    assert manager._list_playlist_video_ids("PL_ALL") == {"v1"}


@pytest.mark.parametrize("response", [None, {"items": {"videoId": "v1"}}])
def test_list_playlist_video_ids_returns_empty_for_invalid_response_shape(manager, response):
    manager._youtube.playlistItems.return_value.list.return_value.execute.return_value = response

    assert manager._list_playlist_video_ids("PL_ALL") == set()
