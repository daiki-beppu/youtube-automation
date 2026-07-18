from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import youtube_automation.scripts.playlist_status as _playlist_status_module

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

        with patch.object(_playlist_status_module, "get_youtube_readonly", return_value=MagicMock()):
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

        with patch.object(_playlist_status_module, "get_youtube_readonly", return_value=MagicMock()):
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

        with patch.object(_playlist_status_module, "get_youtube_readonly", return_value=MagicMock()):
            viewer = _playlist_status_module.PlaylistStatusViewer()
            with patch.object(viewer, "_list_playlist_video_ids", return_value=set()):
                viewer.show_status()

        out = capsys.readouterr().out
        assert "Main Playlist" in out
