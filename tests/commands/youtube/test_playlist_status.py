from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import youtube_automation.commands.youtube.playlist_status as _playlist_status_module
from youtube_automation.core.errors import AuthError

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


class TestShowStatusStringShape:
    def test_show_status_does_not_raise_on_string_shape(self, tmp_path, monkeypatch, capsys):
        ch = _string_shape_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        with patch.object(
            _playlist_status_module,
            "YouTubeClients",
            return_value=SimpleNamespace(youtube_readonly=MagicMock()),
        ):
            viewer = _playlist_status_module.PlaylistStatusViewer()

            with patch.object(viewer, "_list_playlist_video_ids", return_value=set()):
                viewer.show_status()

        out = capsys.readouterr().out
        assert "[main]" in out
        assert PLAYLIST_ID_STRING_SHAPE in out


class TestShowStatusContractDrift:
    """contract-drift 修正の回帰テスト: show_status は正規化済みキーのみ使う."""

    def _dict_shape_channel(self, tmp_path: Path) -> Path:
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
            json.dumps(
                {
                    "playlists": {
                        "main": {
                            "playlist_id": "PL_DICT_SHAPE",
                            "title": "Main Playlist",
                            "auto_add": True,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        return ch

    def test_show_status_uses_playlist_id_key(self, tmp_path, monkeypatch, capsys):
        """show_status が legacy 'id' キーではなく 'playlist_id' キーを使う."""
        ch = self._dict_shape_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        with patch.object(
            _playlist_status_module,
            "YouTubeClients",
            return_value=SimpleNamespace(youtube_readonly=MagicMock()),
        ):
            viewer = _playlist_status_module.PlaylistStatusViewer()
            with patch.object(viewer, "_list_playlist_video_ids", return_value=set()):
                viewer.show_status()

        out = capsys.readouterr().out
        assert "PL_DICT_SHAPE" in out
        assert "[main]" in out

    def test_show_status_uses_title_key(self, tmp_path, monkeypatch, capsys):
        """show_status が legacy 'name' キーではなく 'title' キーを使う."""
        ch = self._dict_shape_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        with patch.object(
            _playlist_status_module,
            "YouTubeClients",
            return_value=SimpleNamespace(youtube_readonly=MagicMock()),
        ):
            viewer = _playlist_status_module.PlaylistStatusViewer()
            with patch.object(viewer, "_list_playlist_video_ids", return_value=set()):
                viewer.show_status()

        out = capsys.readouterr().out
        assert "Main Playlist" in out


class TestShowStatusAuthError:
    """認証失敗は per-playlist の取得エラーに握りつぶさずコマンド失敗へ伝播する（#5235）。"""

    def _viewer(self, tmp_path: Path, monkeypatch):
        ch = TestShowStatusContractDrift()._dict_shape_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))
        with patch.object(
            _playlist_status_module,
            "YouTubeClients",
            return_value=SimpleNamespace(youtube_readonly=MagicMock()),
        ):
            return _playlist_status_module.PlaylistStatusViewer()

    def test_auth_error_propagates_from_show_status(self, tmp_path, monkeypatch, capsys):
        """AuthError は「動画数: (取得エラー)」に変換せずそのまま送出する。"""
        viewer = self._viewer(tmp_path, monkeypatch)
        with patch.object(
            viewer,
            "_list_playlist_video_ids",
            side_effect=AuthError("refresh token が失効しています"),
        ):
            with pytest.raises(AuthError):
                viewer.show_status()

        assert "(取得エラー)" not in capsys.readouterr().out

    def test_main_returns_1_on_auth_error(self, monkeypatch, capsys):
        """main() は AuthError を表示して非 0 で終了する。"""
        viewer = MagicMock()
        viewer.show_status.side_effect = AuthError(
            "refresh token が失効しています。uv run yt-oauth で再認証してください"
        )
        monkeypatch.setattr(_playlist_status_module, "PlaylistStatusViewer", MagicMock(return_value=viewer))

        assert _playlist_status_module.main([]) == 1
        assert "refresh token が失効しています" in capsys.readouterr().out
