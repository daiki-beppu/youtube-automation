#!/usr/bin/env python3
"""
Playlist Manager - YouTube プレイリスト管理

config/channel/playlists.json の playlists 定義に基づき、
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
from pathlib import Path

from youtube_automation.configuration import channel_dir, load_config, reset
from youtube_automation.utils.collection_paths import CollectionPaths
from youtube_automation.utils.cost_tracker import log_quota
from youtube_automation.utils.retry import execute_with_retry
from youtube_automation.utils.youtube_service import get_youtube

logger = logging.getLogger(__name__)

_QUOTA_SERVICE = "youtube-data-api"

# YouTube Data API v3 の quota 単価（units/request）。
# https://developers.google.com/youtube/v3/determine_quota_cost
_QUOTA_UNITS_BY_BUCKET = {
    "playlists.insert": 50,
    "playlistItems.insert": 50,
    "playlistItems.delete": 50,
    "playlistItems.list": 1,
}


def _log_playlist_quota(bucket: str, **metadata) -> None:
    """playlist mutation 経路の quota 消費を 1 request 単位で記録する。

    失敗 request も quota を消費するため、呼び出し側は try/finally で
    成功・失敗の両方から呼ぶ（元例外のフローは変えない）。
    """
    log_quota(
        _QUOTA_SERVICE,
        bucket,
        _QUOTA_UNITS_BY_BUCKET[bucket],
        metadata=metadata or None,
    )


class PlaylistManager:
    """YouTube プレイリスト管理

    config/channel/playlists.json の playlists セクションに基づき、
    プレイリストの CRUD と動画割り当てを管理する。
    """

    def __init__(self):
        self.config = load_config()
        self._config_path = channel_dir() / "config" / "channel" / "playlists.json"
        self._youtube = None

    def _get_youtube(self):
        if self._youtube is None:
            self._youtube = get_youtube()
        return self._youtube

    # ─── YouTube API ラッパ ────────────────────────────

    def _create_playlist(self, title: str, description: str, privacy_status: str = "public") -> dict | None:
        """新規プレイリストを YouTube に作成する。

        Returns:
            成功時: ``{"status": "success", "playlist_id": ..., "playlist_url": ..., "title": ...}``
            失敗時: ``{"status": "failed", "error": ..., "title": ...}``
        """
        youtube = self._get_youtube()
        logger.info(f"📋 Creating playlist: {title}")

        try:
            body = {
                "snippet": {"title": title, "description": description},
                "status": {"privacyStatus": privacy_status},
            }
            request = youtube.playlists().insert(part="snippet,status", body=body)
            try:
                response = execute_with_retry(request, "playlists.insert failed")
            finally:
                _log_playlist_quota("playlists.insert", title=title)
            playlist_id = response["id"]
            playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
            logger.info(f"✅ Playlist created: {playlist_id} ({playlist_url})")
            return {
                "status": "success",
                "playlist_id": playlist_id,
                "playlist_url": playlist_url,
                "title": title,
            }
        except Exception as e:
            logger.error(f"❌ Playlist creation failed: {e}")
            return {"status": "failed", "error": str(e), "title": title}

    def _add_video_to_playlist(self, playlist_id: str, video_id: str, position: int | None = None) -> bool:
        """動画をプレイリストに追加する。

        ``position`` を省略（``None``）すると YouTube API に位置指定を渡さず末尾に追加される。
        ``position`` を整数指定するとその位置に挿入される（0 で先頭）。
        """
        youtube = self._get_youtube()
        where = "末尾" if position is None else f"position={position}"
        logger.info(f"➕ Adding video {video_id} to playlist {playlist_id} ({where})")

        try:
            snippet: dict = {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
            if position is not None:
                snippet["position"] = position
            request = youtube.playlistItems().insert(part="snippet", body={"snippet": snippet})
            try:
                execute_with_retry(request, "playlistItems.insert failed")
            finally:
                _log_playlist_quota("playlistItems.insert", playlist_id=playlist_id, video_id=video_id)
            logger.info(f"✅ Video added to playlist ({where})")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to add video to playlist: {e}")
            return False

    # ─── プレイリスト解決 ──────────────────────────────

    def resolve_playlists(self, theme: str, activity: str | None = None) -> list[str]:
        """テーマから所属すべきプレイリストキーのリストを返す.

        `activity` 明示指定があればそれを優先し、`None` の場合のみ
        `activity_for_theme(theme)` で解決する。明示 override は
        `content.json` 未登録テーマに対する安全弁として使う（#80）。
        """
        playlists_config = self.config.playlists.items
        if activity is None:
            activity = self.config.content.title.activity_for_theme(theme)
        theme_lower = theme.lower()
        matched = []

        for key, pl in playlists_config.items():
            if pl.get("auto_add"):
                matched.append(key)
                continue

            # activity ベースのマッチング（"Study · Focus · Late Night" → ["Study", "Focus", "Late Night"]）
            activities = [a.strip() for a in activity.split("·")]
            if any(a in pl.get("auto_add_activities", []) for a in activities):
                matched.append(key)
                continue

            # theme キーワードベースのマッチング
            for theme_kw in pl.get("auto_add_themes", []):
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
        playlists_config = self.config.playlists.items
        created = {}

        for key, pl in playlists_config.items():
            if pl.get("playlist_id"):
                logger.info(f"  {key}: 既存 ({pl['playlist_id']})")
                continue

            title = pl["title"]
            description = pl.get("description", "")

            if dry_run:
                print(f"  [DRY-RUN] 作成予定: {title}")
                continue

            result = self._create_playlist(title, description)
            if result and result.get("status") == "success":
                playlist_id = result["playlist_id"]
                created[key] = playlist_id
                logger.info(f"  {key}: {playlist_id}")
            else:
                logger.error(f"  {key}: 作成失敗 - {result}")

        if created and not dry_run:
            self._write_back_playlist_ids(created)

        return created

    def _write_back_playlist_ids(self, created: dict[str, str]):
        """config/channel/playlists.json に playlist_id を書き戻す"""
        with open(self._config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        for key, playlist_id in created.items():
            if key in raw.get("playlists", {}):
                raw["playlists"][key]["playlist_id"] = playlist_id

        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
            f.write("\n")

        logger.info(f"config/channel/playlists.json に {len(created)} 件の playlist_id を書き戻しました")

    # ─── 動画割り当て ─────────────────────────────────

    @staticmethod
    def _planning_activities(collection_path: Path) -> str | None:
        """collection_path/workflow-state.json から planning.activities を読む.

        ファイル欠落・JSON 壊れ・キー欠落はいずれも `None` を返して呼び出し側に
        `activity_for_theme` fallback させる（プレイリスト追加は非致命的機能のため）。
        """
        ws_path = CollectionPaths(collection_path).workflow_state_path
        if not ws_path.exists():
            return None
        try:
            data = json.loads(ws_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"workflow-state.json 読み込み失敗 ({ws_path}): {e}")
            return None
        explicit = data.get("planning", {}).get("activities")
        return explicit if isinstance(explicit, str) and explicit else None

    def _list_playlist_video_ids(self, playlist_id: str) -> set[str]:
        """プレイリスト内の動画IDセットを取得（重複防止用）"""
        youtube = self._get_youtube()
        video_ids = set()

        try:
            request = youtube.playlistItems().list(playlistId=playlist_id, part="contentDetails", maxResults=50)
            while request:
                try:
                    response = execute_with_retry(request, "playlistItems.list failed")
                finally:
                    _log_playlist_quota("playlistItems.list", playlist_id=playlist_id)
                for item in response.get("items", []):
                    video_ids.add(item["contentDetails"]["videoId"])
                request = youtube.playlistItems().list_next(request, response)
        except Exception as e:
            logger.warning(f"プレイリスト {playlist_id} の項目取得エラー: {e}")

        return video_ids

    def assign_video(
        self,
        video_id: str,
        theme: str,
        dry_run: bool = False,
        collection_path: Path | None = None,
    ) -> list[str]:
        """単一動画を該当プレイリストに追加

        `collection_path` が与えられた場合、`workflow-state.json` の
        `planning.activities` があればそれを activity override として
        `resolve_playlists` に渡す。`content.json` の `theme_scenes` に
        未登録の新テーマでも、明示的に activity を与えることで正しく
        プレイリスト判定できる（#80）。

        Returns:
            追加先のプレイリストキーリスト
        """
        activity_override = self._planning_activities(collection_path) if collection_path else None
        playlists_config = self.config.playlists.items
        target_keys = self.resolve_playlists(theme, activity=activity_override)
        assigned = []

        for key in target_keys:
            pl = playlists_config[key]
            playlist_id = pl.get("playlist_id")
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

            # "all" プレイリストは末尾追加（position=None）、その他は先頭追加（position=0）
            position = None if key == "all" else 0
            success = self._add_video_to_playlist(playlist_id, video_id, position)

            if success:
                assigned.append(key)

        return assigned

    # ─── 既存動画の一括同期 ────────────────────────────

    def sync_existing_videos(self, dry_run: bool = False) -> dict[str, list[str]]:
        """live/ 配下の全コレクションをプレイリストに割り当て

        Returns:
            {collection_name: [assigned_playlist_keys]}
        """
        collections_dir = channel_dir() / "collections" / "live"
        if not collections_dir.exists():
            logger.warning("live/ ディレクトリが見つかりません")
            return {}

        results = {}
        collections = sorted(collections_dir.iterdir())

        for col_path in collections:
            if not col_path.is_dir() or col_path.name.startswith("."):
                continue

            paths = CollectionPaths(col_path)

            # workflow-state.json からテーマ取得
            ws_path = paths.workflow_state_path
            if not ws_path.exists():
                logger.warning(f"  {col_path.name}: workflow-state.json なし — スキップ")
                continue

            with open(ws_path, "r", encoding="utf-8") as f:
                ws = json.load(f)

            theme = ws.get("theme", "")
            if not theme:
                logger.warning(f"  {col_path.name}: theme 未設定 — スキップ")
                continue

            # upload_tracking.json から video_id 取得
            tracking_path = paths.tracking_path
            if not tracking_path.exists():
                logger.warning(f"  {col_path.name}: upload_tracking.json なし — スキップ")
                continue

            with open(tracking_path, "r", encoding="utf-8") as f:
                tracking = json.load(f)

            video_id = tracking.get("complete_collection", {}).get("video_id")
            if not video_id:
                logger.warning(f"  {col_path.name}: video_id なし — スキップ")
                continue

            # タイトル取得（表示用）
            title = ws.get("steps", {}).get("planning", {}).get("final_title", col_path.name)

            activity_override = self._planning_activities(col_path)

            if dry_run:
                target_keys = self.resolve_playlists(theme, activity=activity_override)
                playlists_config = self.config.playlists.items
                print(f"\n  {title}")
                print(f"    theme: {theme} | video_id: {video_id}")
                for key in target_keys:
                    print(f"    -> {playlists_config[key]['title']}")
                results[col_path.name] = target_keys
            else:
                logger.info(f"\n  {title} ({video_id})")
                assigned = self.assign_video(video_id, theme, collection_path=col_path)
                results[col_path.name] = assigned

        return results

    # ─── 削除済み動画エントリの除去 ────────────────────

    def clean_deleted_entries(self, dry_run: bool = False) -> dict[str, int]:
        """全プレイリストから削除済み/非公開動画のエントリを除去する。

        YouTube は動画が削除/非公開化された後もプレイリスト内にプレースホルダー
        エントリ (snippet.title が "Deleted video" / "Private video") を残す。
        これらを playlistItems.delete で除去する。

        Returns:
            {playlist_key: removed_count}
        """
        youtube = self._get_youtube()
        playlists_config = self.config.playlists.items
        removed_per_playlist: dict[str, int] = {}

        deleted_titles = {"Deleted video", "Private video"}

        for key, pl in playlists_config.items():
            playlist_id = pl.get("playlist_id")
            if not playlist_id:
                logger.info(f"  {key}: playlist_id 未設定 — スキップ")
                continue

            removed = 0
            page_token = None
            while True:
                request = youtube.playlistItems().list(
                    part="snippet",
                    playlistId=playlist_id,
                    maxResults=50,
                    pageToken=page_token,
                )
                try:
                    resp = execute_with_retry(request, "playlistItems.list failed")
                finally:
                    _log_playlist_quota("playlistItems.list", playlist_id=playlist_id)

                for item in resp.get("items", []):
                    title = item["snippet"].get("title", "")
                    if title in deleted_titles:
                        item_id = item["id"]
                        video_id = item["snippet"].get("resourceId", {}).get("videoId", "?")
                        if dry_run:
                            print(f"  [DRY-RUN] {key}: 除去予定 {video_id} ({title})")
                        else:
                            request = youtube.playlistItems().delete(id=item_id)
                            try:
                                execute_with_retry(request, "playlistItems.delete failed")
                            finally:
                                _log_playlist_quota("playlistItems.delete", playlist_id=playlist_id, video_id=video_id)
                            logger.info(f"  {key}: 除去 {video_id} ({title})")
                        removed += 1

                page_token = resp.get("nextPageToken")
                if not page_token:
                    break

            removed_per_playlist[key] = removed
            if removed == 0:
                logger.info(f"  {key}: 削除済みエントリなし")

        return removed_per_playlist

    # ─── init（作成 + 同期） ──────────────────────────

    def init(self, dry_run: bool = False):
        """プレイリスト作成 + 既存動画の一括同期"""
        print("\n=== Step 1: プレイリスト作成 ===")
        self.create_all_playlists(dry_run=dry_run)

        # dry_run でなければ config を再読み込み（書き戻し後の playlist_id を反映）
        if not dry_run:
            reset(preserve_channel_selection=True)
            self.config = load_config()

        print("\n=== Step 2: 既存動画の割り当て ===")
        results = self.sync_existing_videos(dry_run=dry_run)

        total = sum(len(v) for v in results.values())
        print(f"\n=== 完了: {len(results)} コレクション, {total} 件の割り当て ===")


def main():
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    config = load_config()
    parser = argparse.ArgumentParser(description=f"{config.meta.channel_short} Playlist Manager")
    parser.add_argument("--init", action="store_true", help="プレイリスト作成 + 全動画割り当て")
    parser.add_argument("--status", action="store_true", help="現在の状態表示")
    parser.add_argument("--assign", metavar="VIDEO_ID", help="単一動画をプレイリストに追加")
    parser.add_argument("--theme", help="--assign 用のテーマ名")
    parser.add_argument(
        "--clean-deleted", action="store_true", help="全プレイリストから削除済み/非公開動画のエントリを除去"
    )
    parser.add_argument("--dry-run", action="store_true", help="ドライラン（実行せず計画のみ表示）")

    args = parser.parse_args()

    try:
        manager = PlaylistManager()

        if args.init:
            manager.init(dry_run=args.dry_run)
        elif args.status:
            from youtube_automation.scripts.playlist_status import PlaylistStatusViewer

            PlaylistStatusViewer().show_status()
        elif args.clean_deleted:
            print("\n=== 削除済み/非公開動画エントリの除去 ===")
            results = manager.clean_deleted_entries(dry_run=args.dry_run)
            total = sum(results.values())
            print(f"\n=== 完了: {total} 件除去 ===")
            for key, count in results.items():
                if count > 0:
                    print(f"  {key}: {count} 件")
        elif args.assign:
            if not args.theme:
                parser.error("--assign には --theme が必要です")
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
