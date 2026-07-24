"""Canonical public owner of resumable YouTube uploads."""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from youtube_automation.configuration import channel_dir, load_config
from youtube_automation.domains.metadata import BAHMetadataGenerator
from youtube_automation.domains.uploads._complete_collection_strategy import CompleteCollectionMixin
from youtube_automation.domains.uploads._dedup_search import DedupSearchMixin
from youtube_automation.domains.uploads._descriptions_md import DescriptionsMdMixin
from youtube_automation.domains.uploads._preflight import PreflightMixin
from youtube_automation.domains.uploads._uploader_constants import (
    UPLOAD_SOURCE_EXISTING,
    UPLOAD_SOURCE_NEW,
    YOUTUBE_VIDEO_URL_PREFIX,
)
from youtube_automation.domains.uploads.policy import SESSION_EXPIRED_HTTP_STATUSES, RetryDecision, ThumbnailCompression
from youtube_automation.domains.uploads.preflight import check_title_codepoint_limit
from youtube_automation.domains.youtube.channel_settings import build_upload_status_flags
from youtube_automation.infrastructure.errors import (
    AutomationError,
    QuotaExhaustedError,
    UploadError,
    ValidationError,
    YouTubeAPIError,
)
from youtube_automation.infrastructure.filesystem import file_size, path_exists, remove_file
from youtube_automation.infrastructure.google.upload import HttpError, create_media_upload
from youtube_automation.infrastructure.google.youtube import YouTubeClients, execute_youtube_request
from youtube_automation.infrastructure.process import compress_image
from youtube_automation.utils.publish_schedule import resolve_default_publish_at as _resolve_default_publish_at

logger = logging.getLogger(__name__)


def _resume_session_from_persisted_uri(insert_request, resume_session_uri: str) -> None:
    insert_request.resumable_uri = resume_session_uri
    insert_request._in_error_state = True


def _parse_retry_after(resp) -> float | None:
    raw = resp.get("retry-after") if resp is not None else None
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class ResumableUploader:
    """Common resumable upload and thumbnail operations."""

    def __init__(self, youtube_clients):
        self.youtube = None
        self.youtube_clients = youtube_clients

    def initialize(self):
        if self.youtube_clients is None:
            raise TypeError("youtube_clients is required")
        self.youtube = self.youtube_clients.youtube

    def _ensure_service(self):
        if not self.youtube:
            self.initialize()

    def upload_video(
        self,
        video_path: str,
        body: dict,
        thumbnail_path: Optional[str] = None,
        *,
        resume_session_uri: Optional[str] = None,
        on_session_uri_changed: Optional[Callable[[Optional[str]], None]] = None,
        on_upload_complete: Optional[Callable[[], None]] = None,
    ) -> Optional[str]:
        self._ensure_service()
        video_file = Path(video_path)
        if not path_exists(video_file):
            return None
        try:
            request = self.youtube.videos().insert(
                part=",".join(body.keys()),
                body=body,
                media_body=create_media_upload(str(video_file), chunksize=-1, resumable=True),
            )
            if resume_session_uri is not None:
                _resume_session_from_persisted_uri(request, resume_session_uri)
            video_id = self._resumable_upload(request, video_file.name, on_session_uri_changed=on_session_uri_changed)
            if video_id and on_upload_complete is not None:
                on_upload_complete()
            if video_id and thumbnail_path and path_exists(Path(thumbnail_path)):
                self.set_thumbnail(video_id, thumbnail_path)
            return video_id
        except HttpError as e:
            raise YouTubeAPIError(f"動画アップロード API エラー: {e}", status_code=e.resp.status) from e
        except OSError as e:
            raise UploadError(f"ファイルアクセスエラー: {e}") from e

    def _resumable_upload(
        self, insert_request, filename: str, *, on_session_uri_changed: Optional[Callable[[Optional[str]], None]] = None
    ) -> Optional[str]:
        response = None
        attempt = 0
        last_uri = getattr(insert_request, "resumable_uri", None)
        while response is None:
            try:
                _status, response = insert_request.next_chunk()
                current_uri = getattr(insert_request, "resumable_uri", None)
                if on_session_uri_changed and current_uri is not None and current_uri != last_uri:
                    on_session_uri_changed(current_uri)
                    last_uri = current_uri
            except HttpError as e:
                status_code = e.resp.status
                if status_code in SESSION_EXPIRED_HTTP_STATUSES:
                    if on_session_uri_changed:
                        on_session_uri_changed(None)
                    return None
                retry_after = _parse_retry_after(e.resp)
                decision = RetryDecision.for_http_error(status_code, attempt, retry_after_seconds=retry_after)
                if decision.should_retry:
                    time.sleep(decision.delay_seconds)
                    attempt += 1
                elif status_code == 429:
                    raise QuotaExhaustedError(
                        "YouTube API の quota 超過/レート制限。時間をおいて再実行してください",
                        retry_after_seconds=retry_after,
                    ) from e
                else:
                    return None
            except OSError as e:
                raise UploadError(f"アップロードエラー: {e}") from e
        return response.get("id") if "id" in response else None

    def set_thumbnail(self, video_id: str, thumbnail_path: str) -> bool:
        self._ensure_service()
        try:
            thumbnail_file = self._compress_thumbnail(Path(thumbnail_path))
            execute_youtube_request(
                self.youtube.thumbnails().set(videoId=video_id, media_body=create_media_upload(str(thumbnail_file))),
                "thumbnails.set failed",
            )
            if thumbnail_file != Path(thumbnail_path) and path_exists(thumbnail_file):
                remove_file(thumbnail_file)
            return True
        except HttpError as e:
            raise YouTubeAPIError(f"サムネイル設定 API エラー: {e}", status_code=e.resp.status) from e
        except OSError:
            return False

    def _compress_thumbnail(self, thumbnail_path: Path, max_bytes: int = 2_097_152) -> Path:
        strategy = ThumbnailCompression.for_file(file_size(thumbnail_path), max_bytes)
        if not strategy.needs_compression:
            return thumbnail_path
        failed_qualities: set[int] = set()
        while (quality := strategy.next_quality(failed_qualities)) is not None:
            compressed = compress_image(thumbnail_path, [quality], max_bytes)
            if compressed != thumbnail_path:
                return compressed
            failed_qualities.add(quality)
        return thumbnail_path


def _normalize_publish_at(value: str) -> str:
    """`status.publishAt` を YouTube Data API が受け付ける ISO 8601 文字列に正規化する.

    入力例:

    - `"2026-06-15T20:00:00+09:00"` → `"2026-06-15T11:00:00Z"`（UTC 化）
    - `"2026-06-15T11:00:00Z"` → そのまま
    - `"2026-06-15T11:00:00"`（naive） → そのまま（ローカル TZ 仮定）

    Args:
        value: ISO 8601 形式の文字列。

    Returns:
        UTC（Z 終端）に正規化された ISO 8601 文字列。パース失敗時は入力をそのまま返す。
    """
    if not isinstance(value, str):
        return value
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if dt.tzinfo is None:
        # naive datetime は API 側でローカルとして解釈される可能性がある。
        # ここでは入力を尊重しそのまま返す（呼び出し側で TZ aware にする責務）。
        return value
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = [
    "UPLOAD_SOURCE_EXISTING",
    "UPLOAD_SOURCE_NEW",
    "YOUTUBE_VIDEO_URL_PREFIX",
    "ResumableUploader",
    "YouTubeAutoUploader",
]


class YouTubeAutoUploader(
    CompleteCollectionMixin,
    DedupSearchMixin,
    DescriptionsMdMixin,
    PreflightMixin,
    ResumableUploader,
):
    """YouTube自動アップロードメインクラス

    YouTubeUploadCore を継承し、コレクション単位のアップロード機能を提供する。
    コアのアップロード・サムネイル・リトライロジックは YouTubeUploadCore に委譲。
    責務別のロジック（dedup / descriptions.md / preflight / CC 経路）は mixin に分離。
    """

    def __init__(self, collections_root: Optional[str] = None, youtube_clients: YouTubeClients | None = None):
        """
        初期化

        Args:
            collections_root (str): collections/ ディレクトリのパス
        """
        super().__init__(youtube_clients)

        if collections_root is None:
            collections_root = channel_dir() / "collections"

        self.collections_root = Path(collections_root)

    def upload_video(
        self,
        video_path: str,
        metadata: Dict,
        thumbnail_path: Optional[str] = None,
        *,
        resume_session_uri: Optional[str] = None,
        on_session_uri_changed: Optional[Callable[[Optional[str]], None]] = None,
        on_upload_complete: Optional[Callable[[], None]] = None,
    ) -> Optional[str]:
        """
        メタデータ辞書から YouTube API ボディを構築してアップロード

        Args:
            video_path (str): 動画ファイルパス
            metadata (Dict): メタデータ（title, description, tags, privacy_status 等）
            thumbnail_path (str): サムネイルファイルパス
            resume_session_uri: 前回中断時の resumable upload session URI
            on_session_uri_changed: session URI 変化通知コールバック
            on_upload_complete: アップロード成功通知コールバック

        Returns:
            str: アップロードされた動画のID（失敗時はNone）
        """
        # タイトル長バリデーション（YouTube上限100 codepoint）
        title = metadata.get("title", "")
        if msg := check_title_codepoint_limit(title):
            raise ValidationError(msg)

        # リクエストボディ作成
        # AI 開示（containsSyntheticMedia）/ 子供向け申告（selfDeclaredMadeForKids）は
        # config/channel/youtube.json で上書き可能。未設定時は現行の振る舞い
        # （synthetic=True / made_for_kids=False）を維持する (#605)。
        # AI 生成音楽（Lyria / Suno）を主軸とするチャンネルは YouTube の AI 開示
        # （altered or synthetic content）ポリシー上 true を申告する (#603)。
        status_body = {
            "privacyStatus": metadata.get("privacy_status", "private"),
            **build_upload_status_flags(load_config().youtube.api),
        }

        # スケジュール公開: publishAt 指定時は private 必須
        # YouTube Data API は ISO 8601 形式を要求する。`+09:00` のような
        # timezone offset 付き値も受け付けるが、明示的に Z 終端の UTC へ
        # 変換しておくと不要な失敗を避けられる（#647 予約投稿不発の再発防止）。
        if metadata.get("publish_at"):
            normalized = _normalize_publish_at(metadata["publish_at"])
            status_body["privacyStatus"] = "private"
            status_body["publishAt"] = normalized
            logger.info(f"スケジュール公開（private + publishAt={normalized}）")
        else:
            # publishAt 未指定でユーザーが privacy_status="public" を明示している場合、
            # その動画は即時公開される。スケジュール公開を期待していたユーザー向けの
            # 早期可視化として INFO ログを残す（#647）。
            if status_body.get("privacyStatus") == "public":
                logger.info("即時公開: status.privacyStatus=public でアップロードします")

        body = {
            "snippet": {
                "title": metadata["title"],  # YouTube上限100文字
                "description": metadata["description"][:5000],  # YouTube上限5000文字
                "tags": metadata["tags"][:50],  # YouTube上限50タグ
                "categoryId": metadata.get("category_id", "10"),
                "defaultLanguage": metadata.get("language", "en"),
                "defaultAudioLanguage": metadata.get("language", "en"),
            },
            "status": status_body,
        }

        if metadata.get("localizations"):
            body["localizations"] = metadata["localizations"]

        return super().upload_video(
            video_path,
            body,
            thumbnail_path,
            resume_session_uri=resume_session_uri,
            on_session_uri_changed=on_session_uri_changed,
            on_upload_complete=on_upload_complete,
        )

    def upload_collection(
        self,
        collection_path: str,
        publish_at: Optional[str] = None,
        *,
        apply_default_publish_at: bool = True,
        resume_session_uri: Optional[str] = None,
        on_session_uri_changed: Optional[Callable[[Optional[str]], None]] = None,
        on_upload_complete: Optional[Callable[[], None]] = None,
    ) -> Dict:
        """
        Complete Collection のアップロード

        Args:
            collection_path (str): コレクションディレクトリパス
            publish_at (str): スケジュール公開日時（ISO 8601）
            apply_default_publish_at: publish_at 省略時に channel default publish time を適用するか
            resume_session_uri: 前回中断時の resumable upload session URI
            on_session_uri_changed: session URI 変化通知コールバック
            on_upload_complete: アップロード成功通知コールバック

        Returns:
            Dict: アップロード結果
        """
        collection_dir = Path(collection_path)
        from youtube_automation.infrastructure.filesystem import path_exists

        if not path_exists(collection_dir):
            raise FileNotFoundError(f"コレクションディレクトリが見つかりません: {collection_path}")

        self._log_active_channel()
        logger.info(f"🎵 コレクションアップロード開始: {collection_dir.name}")
        logger.info(f"📁 パス: {collection_dir}")

        if publish_at is None and apply_default_publish_at:
            publish_at = _resolve_default_publish_at(load_config())
            if publish_at:
                logger.info(f"チャンネル既定の予約投稿時刻を適用: publish_at={publish_at}")

        # アップロード前メタデータ検証
        self._preflight_check(collection_dir)

        # メタデータ生成器初期化
        metadata_gen = BAHMetadataGenerator(str(collection_dir))

        results = {
            "collection_name": metadata_gen.collection_name,
            "collection_path": str(collection_dir),
            "start_time": datetime.now(),
            "complete_video": None,
            "errors": [],
        }

        # Complete Collection アップロード
        complete_result = self._upload_complete_collection(
            collection_dir,
            metadata_gen,
            publish_at=publish_at,
            resume_session_uri=resume_session_uri,
            on_session_uri_changed=on_session_uri_changed,
            on_upload_complete=on_upload_complete,
        )
        results["complete_video"] = complete_result

        results["end_time"] = datetime.now()
        results["duration"] = results["end_time"] - results["start_time"]

        # 結果レポート
        self._print_upload_report(results)

        return results

    def _log_active_channel(self) -> None:
        """誤投稿防止のため、現在操作対象のチャンネルを明示表示する。"""
        config = load_config()
        parts = [config.meta.channel_name]
        if config.meta.youtube_handle:
            parts.append(config.meta.youtube_handle)
        if config.meta.channel_id:
            parts.append(config.meta.channel_id)
        logger.info(f"🎯 操作中チャンネル: {' / '.join(parts)}")

    def _print_upload_report(self, results: Dict):
        """アップロード結果レポート表示"""
        logger.info("📊 YouTube アップロード結果レポート")
        logger.info(f"🎵 コレクション: {results['collection_name']}")
        logger.info(f"📁 パス: {results['collection_path']}")
        logger.info(f"⏱️  実行時間: {results['duration']}")
        logger.info(f"📅 実行日時: {results['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")

        # Complete Collection 結果
        if results["complete_video"]:
            if "video_id" in results["complete_video"]:
                if results["complete_video"].get("upload_source") == UPLOAD_SOURCE_EXISTING:
                    logger.info(f"⏭️  Complete Collection: 既存動画を流用 {results['complete_video']['video_url']}")
                else:
                    logger.info(f"✅ Complete Collection: {results['complete_video']['video_url']}")
                    self._print_post_upload_manual_checklist(results["complete_video"]["video_url"])
            else:
                logger.error(f"❌ Complete Collection: {results['complete_video']['error']}")

    def _print_post_upload_manual_checklist(self, video_url: str) -> None:
        """YouTube Studio で手動確認が必要な項目をアップロード直後に表示する。"""
        logger.info("📝 アップロード後の手動チェックリスト")
        logger.info("  [ ] YouTube Studio で AI コンテンツの開示設定を確認")
        logger.info("  [ ] YouTube Studio で収益化が ON になっているか確認")
        logger.info(f"  Studio: https://studio.youtube.com/video/{video_url.rsplit('=', 1)[-1]}/edit")

    def process_collections_directory(self, status_filter: Optional[List[str]] = None) -> Dict:
        """
        collections/ ディレクトリ内の対象コレクションを一括処理

        Args:
            status_filter (List[str]): 処理対象ステータス（例: ['ready']）

        Returns:
            Dict: 全体の処理結果
        """
        if status_filter is None:
            status_filter = ["ready"]  # デフォルトはready状態のみ

        config = load_config()
        logger.info(f"🎵 {config.meta.channel_name} - 一括YouTube アップロード")
        logger.info(f"📁 collections ディレクトリ: {self.collections_root}")
        logger.info(f"🎯 対象ステータス: {status_filter}")

        # 対象コレクション検索
        target_collections = []

        for status in status_filter:
            status_dir = self.collections_root / status
            from youtube_automation.infrastructure.filesystem import list_directory, path_exists, path_is_directory

            if path_exists(status_dir):
                collections = [
                    d for d in list_directory(status_dir) if path_is_directory(d) and not d.name.startswith(".")
                ]
                target_collections.extend([(status, col) for col in collections])

        if not target_collections:
            logger.error("❌ 処理対象のコレクションが見つかりません")
            return {"error": "処理対象コレクションなし"}

        logger.info(f"📋 処理対象: {len(target_collections)}コレクション")

        all_results = {
            "start_time": datetime.now(),
            "target_collections": len(target_collections),
            "results": [],
            "summary": {"success": 0, "error": 0},
        }

        # 各コレクションを処理
        for i, (_status, collection_dir) in enumerate(target_collections, 1):
            logger.info(f"🎵 [{i}/{len(target_collections)}] {collection_dir.name}")

            try:
                result = self.upload_collection(str(collection_dir))
                all_results["results"].append(result)

                # 成功判定
                has_success = bool(result.get("complete_video", {}).get("video_id"))

                if has_success:
                    all_results["summary"]["success"] += 1
                    # ready -> live への移動（オプション）
                    # self._move_collection_to_live(collection_dir)
                else:
                    all_results["summary"]["error"] += 1

            except AutomationError:
                error_msg = "collection processing failed"
                logger.error("❌ コレクション処理エラー: %s", collection_dir.name)
                all_results["results"].append({"collection_name": collection_dir.name, "error": error_msg})
                all_results["summary"]["error"] += 1

        all_results["end_time"] = datetime.now()
        all_results["duration"] = all_results["end_time"] - all_results["start_time"]

        # 全体結果レポート
        self._print_batch_report(all_results)

        return all_results

    def _print_batch_report(self, all_results: Dict):
        """一括処理結果レポート"""
        logger.info("🎉 YouTube 一括アップロード完了レポート")
        logger.info(f"📊 処理結果: {all_results['summary']['success']} 成功 / {all_results['summary']['error']} エラー")
        logger.info(f"⏱️  総実行時間: {all_results['duration']}")
        logger.info(f"📅 実行日時: {all_results['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")
