"""
CollectionUploader のユニットテスト

テスト対象: agents/collection_uploader.py

#77 回帰テスト: `_assign_to_playlists()` の import パス誤りで
プレイリスト自動追加が常時失敗していたバグを検出するためのテスト。
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# import smoke test (#77)
# ---------------------------------------------------------------------------


def test_collection_uploader_imports_playlist_manager():
    """collection_uploader は PlaylistManager を正しいパスから import できる。

    #77 の回帰防止: 誤った `from playlist_manager import PlaylistManager` が
    残っているとモジュールロード時点で ImportError になる。
    """
    from youtube_automation.agents import collection_uploader

    assert hasattr(collection_uploader, "PlaylistManager")
    assert collection_uploader.PlaylistManager.__module__ == "youtube_automation.scripts.playlist_manager"


# ---------------------------------------------------------------------------
# _assign_to_playlists
# ---------------------------------------------------------------------------


@pytest.fixture
def workflow_state_file(tmp_path):
    """workflow-state.json を含むコレクションディレクトリを返す"""
    ws_path = tmp_path / "workflow-state.json"
    ws_path.write_text(json.dumps({"theme": "Rainy Jazz"}), encoding="utf-8")
    return tmp_path


def test_assign_to_playlists_calls_playlist_manager(workflow_state_file):
    """`_assign_to_playlists` が PlaylistManager.assign_video を theme 付きで呼ぶ。

    #77 の回帰防止: import パスが正しくなければ以前は ImportError が warning に
    握り潰されて何も呼ばれなかった。
    """
    from youtube_automation.agents.collection_uploader import CollectionUploader

    mock_config = MagicMock()
    mock_config.playlists.items = {"all": {"title": "All", "playlist_id": "PL_ALL"}}

    mock_pm_instance = MagicMock()
    mock_pm_instance.assign_video.return_value = ["all"]

    with (
        patch("youtube_automation.agents.collection_uploader.load_config", return_value=mock_config),
        patch(
            "youtube_automation.agents.collection_uploader.PlaylistManager",
            return_value=mock_pm_instance,
        ) as mock_pm_class,
    ):
        # self を使わないメソッドなので MagicMock インスタンスで十分
        fake_self = MagicMock()
        CollectionUploader._assign_to_playlists(fake_self, "VIDEO_ID_123", workflow_state_file)

    mock_pm_class.assert_called_once_with()
    mock_pm_instance.assign_video.assert_called_once_with(
        "VIDEO_ID_123", "Rainy Jazz", collection_path=workflow_state_file
    )


def test_assign_to_playlists_skips_when_no_theme(tmp_path):
    """theme が空なら PlaylistManager を呼ばずに return する"""
    from youtube_automation.agents.collection_uploader import CollectionUploader

    ws_path = tmp_path / "workflow-state.json"
    ws_path.write_text(json.dumps({"theme": ""}), encoding="utf-8")

    with (
        patch("youtube_automation.agents.collection_uploader.load_config") as mock_load,
        patch("youtube_automation.agents.collection_uploader.PlaylistManager") as mock_pm_class,
    ):
        fake_self = MagicMock()
        CollectionUploader._assign_to_playlists(fake_self, "VIDEO_ID_123", tmp_path)

    mock_load.assert_not_called()
    mock_pm_class.assert_not_called()


def test_assign_to_playlists_skips_when_no_workflow_state(tmp_path):
    """workflow-state.json がなければ何もしない"""
    from youtube_automation.agents.collection_uploader import CollectionUploader

    with (
        patch("youtube_automation.agents.collection_uploader.load_config") as mock_load,
        patch("youtube_automation.agents.collection_uploader.PlaylistManager") as mock_pm_class,
    ):
        fake_self = MagicMock()
        CollectionUploader._assign_to_playlists(fake_self, "VIDEO_ID_123", tmp_path)

    mock_load.assert_not_called()
    mock_pm_class.assert_not_called()
