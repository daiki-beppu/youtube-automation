#!/usr/bin/env python3
"""
Playlist Manager - YouTube プレイリスト管理

channel_config.json の playlists 定義に基づき、
プレイリストの作成・動画割り当て・状態管理を行う。

Usage:
    python3 automation/playlist_manager.py --init              # 作成 + 全動画割り当て
    python3 automation/playlist_manager.py --init --dry-run    # ドライラン
    python3 automation/playlist_manager.py --assign VIDEO_ID --theme THEME
    python3 automation/playlist_manager.py --status            # 現在の状況表示
"""

import json
import logging
import sys

from youtube_automation.scripts.video_uploader import VideoUploader
from youtube_automation.utils.channel_config import ChannelConfig
from youtube_automation.utils.youtube_service import get_youtube

logger = logging.getLogger(__name__)


class PlaylistManager:
    """YouTube プレイリスト管理

    channel_config.json の playlists セクションに基づき、
    プレイリストの CRUD と動画割り当てを管理する。
    """

    def __init__(self):
        self.config = ChannelConfig.load()
        self.uploader = VideoUploader()
        self._config_path = ChannelConfig.channel_dir() / 'config' / 'channel_config.json'
        self._youtube = None

    def _get_youtube(self):
        if self._youtube is None:
            self._youtube = get_youtube()
        return self._youtube

    # ─── プレイリスト解決 ──────────────────────────────

    def resolve_playlists(self, theme: str) -> list[str]:
        """テーマから所属すべきプレイリストキーのリストを返す"""
        playlists_config = self.config.playlists
        activity = self.config.get_activity_for_theme(theme)
        theme_lower = theme.lower()
        matched = []

        for key, pl in playlists_config.items():
            if pl.get('auto_add'):
                matched.append(key)
                continue

            # activity ベースのマッチング（"Study · Focus · Late Night" → ["Study", "Focus", "Late Night"]）
            activities = [a.strip() for a in activity.split('·')]
            if any(a in pl.get('auto_add_activities', []) for a in activities):
                matched.append(key)
                continue

            # theme キーワードベースのマッチング
            for theme_kw in pl.get('auto_add_themes', []):
                if theme_kw in theme_lower:
                    matched.append(key)
                    break

        return matched

    # ─── プレイリスト作成 ──────────────────────────────

    def create_all_playlists(self, dry_run: bool = False) -> dict[str, str]:
        """playlist_id が未設定のプレイリストを YouTube に作成

        Returns:
            作成されたプレイリストの {key: playlist_id} マップ
        """
        playlists_config = self.config.playlists
        created = {}

        for key, pl in playlists_config.items():
            if pl.get('playlist_id'):
                logger.info(f"  {key}: 既存 ({pl['playlist_id']})")
                continue

            title = pl['title']
            description = pl.get('description', '')

            if dry_run:
                print(f"  [DRY-RUN] 作成予定: {title}")
                continue

            result = self.uploader.create_playlist(title, description)
            if result and result.get('status') == 'success':
                playlist_id = result['playlist_id']
                created[key] = playlist_id
                logger.info(f"  {key}: {playlist_id}")
            else:
                logger.error(f"  {key}: 作成失敗 - {result}")

        if created and not dry_run:
            self._write_back_playlist_ids(created)

        return created

    def _write_back_playlist_ids(self, created: dict[str, str]):
        """channel_config.json に playlist_id を書き戻す"""
        with open(self._config_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        for key, playlist_id in created.items():
            if key in raw.get('playlists', {}):
                raw['playlists'][key]['playlist_id'] = playlist_id

        with open(self._config_path, 'w', encoding='utf-8') as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
            f.write('\n')

        logger.info(f"channel_config.json に {len(created)} 件の playlist_id を書き戻しました")

    # ─── 動画割り当て ─────────────────────────────────

    def _list_playlist_video_ids(self, playlist_id: str) -> set[str]:
        """プレイリスト内の動画IDセットを取得（重複防止用）"""
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

    def assign_video(self, video_id: str, theme: str, dry_run: bool = False) -> list[str]:
        """単一動画を該当プレイリストに追加

        Returns:
            追加先のプレイリストキーリスト
        """
        playlists_config = self.config.playlists
        target_keys = self.resolve_playlists(theme)
        assigned = []

        for key in target_keys:
            pl = playlists_config[key]
            playlist_id = pl.get('playlist_id')
            if not playlist_id:
                logger.warning(f"  {key}: playlist_id 未設定 — スキップ")
                continue

            if dry_run:
                print(f"  [DRY-RUN] {video_id} -> {pl['title']}")
                assigned.append(key)
                continue

            # 重複チェック
            existing = self._list_playlist_video_ids(playlist_id)
            if video_id in existing:
                logger.info(f"  {key}: {video_id} は既に追加済み")
                assigned.append(key)
                continue

            # "all" プレイリストは末尾追加、その他は先頭追加
            position = None if key == 'all' else 0

            if position is not None:
                success = self.uploader.add_video_to_playlist(playlist_id, video_id, position)
            else:
                success = self._add_video_to_playlist_end(playlist_id, video_id)

            if success:
                assigned.append(key)

        return assigned

    def _add_video_to_playlist_end(self, playlist_id: str, video_id: str) -> bool:
        """プレイリスト末尾に動画を追加（position を省略して API に任せる）"""
        if not self.uploader.youtube:
            self.uploader.authenticate()

        try:
            body = {
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id
                    }
                }
            }
            self.uploader.youtube.playlistItems().insert(
                part="snippet", body=body
            ).execute()
            logger.info(f"  {video_id} -> {playlist_id} (末尾)")
            return True
        except Exception as e:
            logger.error(f"  プレイリスト追加失敗: {e}")
            return False

    # ─── 既存動画の一括同期 ────────────────────────────

    def sync_existing_videos(self, dry_run: bool = False) -> dict[str, list[str]]:
        """live/ 配下の全コレクションをプレイリストに割り当て

        Returns:
            {collection_name: [assigned_playlist_keys]}
        """
        collections_dir = ChannelConfig.channel_dir() / 'collections' / 'live'
        if not collections_dir.exists():
            logger.warning("live/ ディレクトリが見つかりません")
            return {}

        results = {}
        collections = sorted(collections_dir.iterdir())

        for col_path in collections:
            if not col_path.is_dir() or col_path.name.startswith('.'):
                continue

            # workflow-state.json からテーマ取得
            ws_path = col_path / 'workflow-state.json'
            if not ws_path.exists():
                logger.warning(f"  {col_path.name}: workflow-state.json なし — スキップ")
                continue

            with open(ws_path, 'r', encoding='utf-8') as f:
                ws = json.load(f)

            theme = ws.get('theme', '')
            if not theme:
                logger.warning(f"  {col_path.name}: theme 未設定 — スキップ")
                continue

            # upload_tracking.json から video_id 取得
            tracking_path = col_path / '20-documentation' / 'upload_tracking.json'
            if not tracking_path.exists():
                logger.warning(f"  {col_path.name}: upload_tracking.json なし — スキップ")
                continue

            with open(tracking_path, 'r', encoding='utf-8') as f:
                tracking = json.load(f)

            video_id = tracking.get('complete_collection', {}).get('video_id')
            if not video_id:
                logger.warning(f"  {col_path.name}: video_id なし — スキップ")
                continue

            # タイトル取得（表示用）
            title = ws.get('steps', {}).get('planning', {}).get('final_title', col_path.name)

            if dry_run:
                target_keys = self.resolve_playlists(theme)
                playlists_config = self.config.playlists
                print(f"\n  {title}")
                print(f"    theme: {theme} | video_id: {video_id}")
                for key in target_keys:
                    print(f"    -> {playlists_config[key]['title']}")
                results[col_path.name] = target_keys
            else:
                logger.info(f"\n  {title} ({video_id})")
                assigned = self.assign_video(video_id, theme)
                results[col_path.name] = assigned

        return results

    # ─── init（作成 + 同期） ──────────────────────────

    def init(self, dry_run: bool = False):
        """プレイリスト作成 + 既存動画の一括同期"""
        print("\n=== Step 1: プレイリスト作成 ===")
        self.create_all_playlists(dry_run=dry_run)

        # dry_run でなければ config を再読み込み（書き戻し後の playlist_id を反映）
        if not dry_run:
            ChannelConfig.reset()
            self.config = ChannelConfig.load()

        print("\n=== Step 2: 既存動画の割り当て ===")
        results = self.sync_existing_videos(dry_run=dry_run)

        total = sum(len(v) for v in results.values())
        print(f"\n=== 完了: {len(results)} コレクション, {total} 件の割り当て ===")


def main():
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    config = ChannelConfig.load()
    parser = argparse.ArgumentParser(description=f'{config.channel_short} Playlist Manager')
    parser.add_argument('--init', action='store_true', help='プレイリスト作成 + 全動画割り当て')
    parser.add_argument('--status', action='store_true', help='現在の状態表示')
    parser.add_argument('--assign', metavar='VIDEO_ID', help='単一動画をプレイリストに追加')
    parser.add_argument('--theme', help='--assign 用のテーマ名')
    parser.add_argument('--dry-run', action='store_true', help='ドライラン（実行せず計画のみ表示）')

    args = parser.parse_args()

    try:
        manager = PlaylistManager()

        if args.init:
            manager.init(dry_run=args.dry_run)
        elif args.status:
            from playlist_status import PlaylistStatusViewer
            PlaylistStatusViewer().show_status()
        elif args.assign:
            if not args.theme:
                parser.error('--assign には --theme が必要です')
            assigned = manager.assign_video(args.assign, args.theme, dry_run=args.dry_run)
            print(f"割り当て: {assigned}")
        else:
            parser.print_help()

    except KeyboardInterrupt:
        print("\n中断されました")
    except Exception as e:
        print(f"エラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
