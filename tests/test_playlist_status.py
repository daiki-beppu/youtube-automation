"""PlaylistStatusViewer のリグレッションテスト.

issue #275: string-shape `playlists.json` でも `show_status` が AttributeError を
出さずに動作することを担保する。`MagicMock` ではなく実 `load_config()` で
組み立てた `ChannelConfig` を viewer に注入することで、loader → consumer の
契約を verify する。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

# Python 3.14 互換: `patch("youtube_automation.scripts.playlist_status.X")` は
# モジュールを attribute 解決するため、事前に submodule を import しておく。
import youtube_automation.scripts.playlist_status as _playlist_status_module  # noqa: E402

PLAYLIST_ID_STRING_SHAPE = "PL_test_string_275"


def _string_shape_channel(tmp_path: Path) -> Path:
    """string-shape playlists.json を持つ最小チャンネル fixture を tmp 配下に作る."""
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
    """#275: `yt-playlist-status` CLI 経由でも string-shape で落ちないこと."""

    def test_show_status_does_not_raise_on_string_shape(self, tmp_path, monkeypatch, capsys):
        """string-shape entry でも show_status は AttributeError を出さず ID 行を出力する."""
        # Given
        ch = _string_shape_channel(tmp_path)
        monkeypatch.setenv("CHANNEL_DIR", str(ch))

        with patch.object(
            _playlist_status_module, "get_youtube", return_value=MagicMock()
        ):
            viewer = _playlist_status_module.PlaylistStatusViewer()

            # When
            with patch.object(viewer, "_list_playlist_video_ids", return_value=set()):
                viewer.show_status()

        # Then
        out = capsys.readouterr().out
        assert "[main]" in out
        assert PLAYLIST_ID_STRING_SHAPE in out
