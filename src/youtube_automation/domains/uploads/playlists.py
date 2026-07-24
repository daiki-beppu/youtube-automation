"""YouTube playlist upload operations owned by the uploads domain."""

import json
import logging
from pathlib import Path
from typing import Protocol

from youtube_automation.configuration import channel_dir, load_config, reset
from youtube_automation.infrastructure.errors import ValidationError, YouTubeAPIError
from youtube_automation.infrastructure.filesystem import (
    list_directory,
    path_exists,
    path_is_directory,
    read_json,
    write_json,
)
from youtube_automation.infrastructure.google.youtube import execute_youtube_request, validate_youtube_response_items
from youtube_automation.infrastructure.quota import youtube_quota_recorder
from youtube_automation.utils.collection_paths import CollectionPaths

logger = logging.getLogger(__name__)


class _YouTubeClientScope(Protocol):
    @property
    def youtube(self): ...


_QUOTA_UNITS_BY_BUCKET = {
    "playlists.insert": 50,
    "playlistItems.insert": 50,
    "playlistItems.delete": 50,
    "playlistItems.list": 1,
}


def _log_playlist_quota(bucket: str, **metadata):
    return youtube_quota_recorder(bucket, _QUOTA_UNITS_BY_BUCKET[bucket], metadata=metadata or None)


class PlaylistManager:
    """YouTube プレイリスト管理

    config/channel/playlists.json の playlists セクションに基づき、
    プレイリストの CRUD と動画割り当てを管理する。
    """

    def __init__(self, clients: _YouTubeClientScope | None = None):
        self.config = load_config()
        self._config_path = channel_dir() / "config" / "channel" / "playlists.json"
        self._youtube = None
        self._youtube_clients = clients

    def _youtube_service(self):
        if self._youtube_clients is None:
            raise RuntimeError("PlaylistManager requires an injected YouTubeClients instance")
        if self._youtube is None:
            self._youtube = self._youtube_clients.youtube
        return self._youtube

    # ─── YouTube API ラッパ ────────────────────────────

    def _create_playlist(self, title: str, description: str, privacy_status: str = "public") -> dict | None:
        """新規プレイリストを YouTube に作成する。

        Returns:
            成功時: ``{"status": "success", "playlist_id": ..., "playlist_url": ..., "title": ...}``
            失敗時: ``{"status": "failed", "error": ..., "title": ...}``
        """
        youtube = self._youtube_service()
        logger.info(f"📋 Creating playlist: {title}")

        try:
            body = {
                "snippet": {"title": title, "description": description},
                "status": {"privacyStatus": privacy_status},
            }
            request = youtube.playlists().insert(part="snippet,status", body=body)
            response = execute_youtube_request(
                request,
                "playlists.insert failed",
                on_attempt=_log_playlist_quota("playlists.insert", title=title),
            )
            playlist_id = response.get("id") if isinstance(response, dict) else None
            if not isinstance(playlist_id, str) or not playlist_id:
                raise ValidationError("playlists.insert response is missing id")
            playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
            logger.info(f"✅ Playlist created: {playlist_id} ({playlist_url})")
            return {
                "status": "success",
                "playlist_id": playlist_id,
                "playlist_url": playlist_url,
                "title": title,
            }
        except (TypeError, ValueError, OSError, ValidationError, YouTubeAPIError) as e:
            logger.error(f"❌ Playlist creation failed: {e}")
            return {"status": "failed", "error": str(e), "title": title}

    def _add_video_to_playlist(self, playlist_id: str, video_id: str, position: int | None = None) -> bool:
        """動画をプレイリストに追加する。

        ``position`` を省略（``None``）すると YouTube API に位置指定を渡さず末尾に追加される。
        ``position`` を整数指定するとその位置に挿入される（0 で先頭）。
        """
        youtube = self._youtube_service()
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
            execute_youtube_request(
                request,
                "playlistItems.insert failed",
                on_attempt=_log_playlist_quota("playlistItems.insert", playlist_id=playlist_id, video_id=video_id),
            )
            logger.info(f"✅ Video added to playlist ({where})")
            return True
        except (TypeError, ValueError, OSError, ValidationError, YouTubeAPIError) as e:
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
        raw = read_json(self._config_path)

        for key, playlist_id in created.items():
            if key in raw.get("playlists", {}):
                raw["playlists"][key]["playlist_id"] = playlist_id

        write_json(self._config_path, raw)

        logger.info(f"config/channel/playlists.json に {len(created)} 件の playlist_id を書き戻しました")

    # ─── 動画割り当て ─────────────────────────────────

    @staticmethod
    def _planning_activities(collection_path: Path) -> str | None:
        """collection_path/workflow-state.json から planning.activities を読む.

        ファイル欠落・JSON 壊れ・キー欠落はいずれも `None` を返して呼び出し側に
        `activity_for_theme` fallback させる（プレイリスト追加は非致命的機能のため）。
        """
        ws_path = CollectionPaths(collection_path).workflow_state_path
        if not path_exists(ws_path):
            return None
        try:
            data = read_json(ws_path)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"workflow-state.json 読み込み失敗 ({ws_path}): {e}")
            return None
        explicit = data.get("planning", {}).get("activities")
        return explicit if isinstance(explicit, str) and explicit else None

    def _list_playlist_video_ids(self, playlist_id: str) -> set[str]:
        """プレイリスト内の動画IDセットを取得（重複防止用）"""
        youtube = self._youtube_service()
        video_ids = set()

        try:
            request = youtube.playlistItems().list(playlistId=playlist_id, part="contentDetails", maxResults=50)
            while request:
                response = execute_youtube_request(
                    request,
                    "playlistItems.list failed",
                    on_attempt=_log_playlist_quota("playlistItems.list", playlist_id=playlist_id),
                )
                for item in validate_youtube_response_items(response, "playlistItems.list"):
                    if not isinstance(item, dict):
                        raise ValidationError("playlistItems.list response item must be an object")
                    content_details = item.get("contentDetails")
                    video_id = content_details.get("videoId") if isinstance(content_details, dict) else None
                    if not isinstance(video_id, str) or not video_id:
                        raise ValidationError("playlistItems.list response is missing contentDetails.videoId")
                    video_ids.add(video_id)
                request = youtube.playlistItems().list_next(request, response)
        except (TypeError, ValueError, OSError, ValidationError, YouTubeAPIError) as e:
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
        if not path_exists(collections_dir):
            logger.warning("live/ ディレクトリが見つかりません")
            return {}

        results = {}
        collections = sorted(list_directory(collections_dir))

        for col_path in collections:
            if not path_is_directory(col_path) or col_path.name.startswith("."):
                continue

            paths = CollectionPaths(col_path)

            # workflow-state.json からテーマ取得
            ws_path = paths.workflow_state_path
            if not path_exists(ws_path):
                logger.warning(f"  {col_path.name}: workflow-state.json なし — スキップ")
                continue

            ws = read_json(ws_path)

            theme = ws.get("theme", "")
            if not theme:
                logger.warning(f"  {col_path.name}: theme 未設定 — スキップ")
                continue

            # upload_tracking.json から video_id 取得
            tracking_path = paths.tracking_path
            if not path_exists(tracking_path):
                logger.warning(f"  {col_path.name}: upload_tracking.json なし — スキップ")
                continue

            tracking = read_json(tracking_path)

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
        youtube = self._youtube_service()
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
                resp = execute_youtube_request(
                    request,
                    "playlistItems.list failed",
                    on_attempt=_log_playlist_quota("playlistItems.list", playlist_id=playlist_id),
                )

                for item in validate_youtube_response_items(resp, "playlistItems.list"):
                    if not isinstance(item, dict) or not isinstance(item.get("snippet"), dict):
                        raise ValidationError("playlistItems.list response is missing snippet")
                    snippet = item["snippet"]
                    title = snippet.get("title", "")
                    if title in deleted_titles:
                        item_id = item.get("id")
                        if not isinstance(item_id, str) or not item_id:
                            raise ValidationError("playlistItems.list response is missing id")
                        resource_id = snippet.get("resourceId") or {}
                        video_id = resource_id.get("videoId", "?") if isinstance(resource_id, dict) else "?"
                        if dry_run:
                            print(f"  [DRY-RUN] {key}: 除去予定 {video_id} ({title})")
                        else:
                            request = youtube.playlistItems().delete(id=item_id)
                            execute_youtube_request(
                                request,
                                "playlistItems.delete failed",
                                on_attempt=_log_playlist_quota(
                                    "playlistItems.delete", playlist_id=playlist_id, video_id=video_id
                                ),
                            )
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
