#!/usr/bin/env python3
"""
Playlist Status Viewer - プレイリスト状態表示

config/channel/playlists.json の playlists 定義に基づき、
プレイリストの現在の状態を表示する。

Usage:
    python3 automation/playlist_status.py
"""

import contextlib
import logging
import sys

from youtube_automation.configuration import load_config
from youtube_automation.utils import cost_tracker
from youtube_automation.utils.youtube_service import get_youtube_readonly

logger = logging.getLogger(__name__)

_QUOTA_SERVICE = "youtube-data-api"
_READ_QUOTA_UNITS = 1


def _record_read_quota(bucket: str) -> None:
    """read 1 リクエスト分の quota 消費を記録する。記録失敗で元の処理は止めない。"""
    try:
        with contextlib.redirect_stdout(sys.stderr):
            cost_tracker.log_quota(_QUOTA_SERVICE, bucket, _READ_QUOTA_UNITS)
    except Exception:
        logger.debug("quota 記録失敗 (bucket=%s)", bucket)


class PlaylistStatusViewer:
    """プレイリスト状態表示"""

    def __init__(self):
        self.config = load_config()
        self._youtube = None

    def _get_youtube(self):
        if self._youtube is None:
            self._youtube = get_youtube_readonly()
        return self._youtube

    def _list_playlist_video_ids(self, playlist_id: str) -> set[str]:
        """プレイリスト内の動画IDセットを取得"""
        youtube = self._get_youtube()
        video_ids = set()

        try:
            request = youtube.playlistItems().list(playlistId=playlist_id, part="contentDetails", maxResults=50)
            while request:
                try:
                    # pagination の 1 ページ = 1 リクエストごとに quota を記録する
                    response = request.execute()
                finally:
                    _record_read_quota("playlistItems.list")
                for item in response.get("items", []):
                    video_ids.add(item["contentDetails"]["videoId"])
                request = youtube.playlistItems().list_next(request, response)
        except Exception as e:
            logger.warning(f"プレイリスト {playlist_id} の項目取得エラー: {e}")

        return video_ids

    def show_status(self):
        """プレイリストの現在の状態を表示"""
        playlists_config = self.config.playlists.items

        if not playlists_config:
            print("playlists セクションが config/channel/playlists.json に未定義です")
            return

        print(f"\n{self.config.meta.channel_name} - Playlists")
        print("=" * 50)

        for key, pl in playlists_config.items():
            playlist_id = pl.get("playlist_id")
            status = playlist_id or "(未作成)"
            title = pl.get("title") or f"Playlist {key}"
            print(f"\n  [{key}] {title}")
            print(f"    ID: {status}")

            if playlist_id:
                try:
                    video_ids = self._list_playlist_video_ids(playlist_id)
                    print(f"    動画数: {len(video_ids)}")
                except Exception:
                    print("    動画数: (取得エラー)")

            # マッチングルール表示
            if pl.get("auto_add"):
                print("    ルール: 全動画自動追加")
            if pl.get("auto_add_activities"):
                print(f"    ルール: activities = {pl['auto_add_activities']}")
            if pl.get("auto_add_themes"):
                print(f"    ルール: themes = {pl['auto_add_themes']}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        viewer = PlaylistStatusViewer()
        viewer.show_status()
    except KeyboardInterrupt:
        print("\n中断されました")
    except Exception as e:
        print(f"エラー: {e}")
        import sys

        sys.exit(1)


if __name__ == "__main__":
    main()
