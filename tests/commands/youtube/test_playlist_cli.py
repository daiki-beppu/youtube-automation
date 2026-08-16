"""Playlist command adapter の実行時契約。"""

from unittest.mock import MagicMock

import pytest

from youtube_automation.commands.youtube import playlist_manager, playlist_status
from youtube_automation.core.errors import YouTubeAPIError


def _manager_cli(monkeypatch):
    manager = MagicMock()
    manager.clean_deleted_entries.return_value = {"first": 2, "second": 1}
    manager.assign_video.return_value = ["all", "focus"]
    manager_class = MagicMock(return_value=manager)
    clients = MagicMock(return_value=object())
    handler = MagicMock(return_value=object())
    monkeypatch.setattr(playlist_manager, "PlaylistManager", manager_class)
    monkeypatch.setattr(playlist_manager, "YouTubeClients", clients)
    monkeypatch.setattr(playlist_manager, "YouTubeOAuthHandler", handler)
    return manager, manager_class, clients, handler


def test_manager_cli_init_forwards_dry_run(monkeypatch):
    manager, manager_class, clients, handler = _manager_cli(monkeypatch)

    assert playlist_manager.main(["--init", "--dry-run"]) == 0

    handler.assert_called_once_with()
    clients.assert_called_once_with(full_handler=handler.return_value)
    manager_class.assert_called_once_with(clients=clients.return_value)
    manager.init.assert_called_once_with(dry_run=True)


def test_manager_cli_status_uses_viewer_without_full_auth(monkeypatch):
    _, manager_class, clients, handler = _manager_cli(monkeypatch)
    viewer = MagicMock()
    monkeypatch.setattr(playlist_status, "PlaylistStatusViewer", MagicMock(return_value=viewer))

    assert playlist_manager.main(["--status"]) == 0

    viewer.show_status.assert_called_once_with()
    manager_class.assert_not_called()
    clients.assert_not_called()
    handler.assert_not_called()


def test_manager_cli_clean_deleted_prints_total(monkeypatch, capsys):
    manager, _, _, _ = _manager_cli(monkeypatch)

    assert playlist_manager.main(["--clean-deleted", "--dry-run"]) == 0

    manager.clean_deleted_entries.assert_called_once_with(dry_run=True)
    assert capsys.readouterr().out == "完了: 3 件除去\n"


def test_manager_cli_assign_forwards_video_theme_and_dry_run(monkeypatch, capsys):
    manager, _, _, _ = _manager_cli(monkeypatch)

    assert playlist_manager.main(["--assign", "VIDEO123", "--theme", "night cafe", "--dry-run"]) == 0

    manager.assign_video.assert_called_once_with("VIDEO123", "night cafe", dry_run=True, collection_path=None)
    assert capsys.readouterr().out == "割り当て: ['all', 'focus']\n"


def test_manager_cli_rejects_assign_without_theme_before_auth(monkeypatch, capsys):
    _, manager_class, clients, handler = _manager_cli(monkeypatch)

    with pytest.raises(SystemExit) as error:
        playlist_manager.main(["--assign", "VIDEO123"])

    assert error.value.code == 2
    assert "--assign には --theme が必要です" in capsys.readouterr().err
    manager_class.assert_not_called()
    clients.assert_not_called()
    handler.assert_not_called()


def test_manager_cli_returns_one_for_domain_error(monkeypatch, capsys):
    manager, _, _, _ = _manager_cli(monkeypatch)
    manager.init.side_effect = YouTubeAPIError("quota exceeded")

    assert playlist_manager.main(["--init"]) == 1
    assert capsys.readouterr().err == "エラー: quota exceeded\n"


def test_status_cli_runs_viewer(monkeypatch):
    viewer = MagicMock()
    monkeypatch.setattr(playlist_status, "PlaylistStatusViewer", MagicMock(return_value=viewer))

    assert playlist_status.main([]) == 0
    viewer.show_status.assert_called_once_with()


def test_status_cli_keyboard_interrupt_is_clean_exit(monkeypatch, capsys):
    viewer = MagicMock()
    viewer.show_status.side_effect = KeyboardInterrupt
    monkeypatch.setattr(playlist_status, "PlaylistStatusViewer", MagicMock(return_value=viewer))

    assert playlist_status.main([]) == 0
    assert "中断されました" in capsys.readouterr().out


def test_status_cli_external_failure_returns_one(monkeypatch, capsys):
    monkeypatch.setattr(
        playlist_status,
        "PlaylistStatusViewer",
        MagicMock(side_effect=RuntimeError("API unavailable")),
    )

    assert playlist_status.main([]) == 1
    assert capsys.readouterr().out == "エラー: API unavailable\n"
