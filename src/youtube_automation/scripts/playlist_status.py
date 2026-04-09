#!/usr/bin/env python3
"""
Playlist Status Viewer - プレイリスト状態表示

channel_config.json の playlists 定義に基づき、
プレイリストの現在の状態を表示する。

Usage:
    python3 automation/playlist_status.py
"""

import logging

from youtube_automation.utils.channel_config import ChannelConfig  # noqa: E402
from youtube_automation.utils.youtube_service import get_youtube  # noqa: E402

logger = logging.getLogger(__name__)


class PlaylistStatusViewer:
    """プレイリスト状態表示"""

    def __init__(self):
        self.config = ChannelConfig.load()
        self._youtube = None

    def _get_youtube(self):
        if self._youtube is None:
            self._youtube = get_youtube()
        return self._youtube

    def _list_playlist_video_ids(self, playlist_id: str) -> set[str]:
        """プレイリスト内の動画IDセットを取得"""
        youtube = self._get_youtube()
        video_ids = set()

        try:
            request = youtube.playlistItems().list(
                playlistId=playlist_id, part='contentDetails', maxResults=50
            )
            while request:
                response = request.execute()
                for item in response.get('items', []):
                    video_ids.add(item['contentDetails']['videoId'])
                request = youtube.playlistItems().list_next(request, response)
        except Exception as e:
            logger.warning(f"プレイリスト {playlist_id} の項目取得エラー: {e}")

        return video_ids

    def show_status(self):
        """プレイリストの現在の状態を表示"""
        playlists_config = self.config.playlists

        if not playlists_config:
            print("playlists セクションが channel_config.json に未定義です")
            return

        print(f"\n{self.config.channel_name} - Playlists")
        print("=" * 50)

        for key, pl in playlists_config.items():
            playlist_id = pl.get('playlist_id')
            status = playlist_id or "(未作成)"
            print(f"\n  [{key}] {pl['title']}")
            print(f"    ID: {status}")

            if playlist_id:
                try:
                    video_ids = self._list_playlist_video_ids(playlist_id)
                    print(f"    動画数: {len(video_ids)}")
                except Exception:
                    print("    動画数: (取得エラー)")

            # マッチングルール表示
            if pl.get('auto_add'):
                print("    ルール: 全動画自動追加")
            if pl.get('auto_add_activities'):
                print(f"    ルール: activities = {pl['auto_add_activities']}")
            if pl.get('auto_add_themes'):
                print(f"    ルール: themes = {pl['auto_add_themes']}")


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
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
