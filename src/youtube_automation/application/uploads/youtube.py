"""Compose channel configuration, preflight, metadata and collection uploads."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from youtube_automation.application.metadata.service import BAHMetadataGenerator
from youtube_automation.application.uploads.preflight import PreflightChecker
from youtube_automation.configuration import load_config
from youtube_automation.core.channel_context import channel_dir
from youtube_automation.core.errors import (
    AutomationError,
    ConfigError,
    ValidationError,
    YouTubeAPIError,
)
from youtube_automation.domains.uploads._complete_collection_strategy import CompleteCollectionStrategy
from youtube_automation.domains.uploads._dedup_search import DedupSearch
from youtube_automation.domains.uploads._uploader_constants import (
    UPLOAD_SOURCE_EXISTING,
    UPLOAD_SOURCE_NEW,
    YOUTUBE_VIDEO_URL_PREFIX,
)
from youtube_automation.domains.uploads.preflight import check_title_codepoint_limit, ensure_collection_preflight
from youtube_automation.domains.uploads.scheduling import resolve_default_publish_at as _resolve_default_publish_at
from youtube_automation.domains.uploads.youtube import ResumableUploader
from youtube_automation.domains.youtube.channel_settings import build_upload_status_flags
from youtube_automation.infrastructure.google.youtube import (
    YouTubeClients,
    execute_youtube_request,
    validate_youtube_response_items,
)

logger = logging.getLogger("youtube_automation.domains.uploads.youtube")

__all__ = [
    "UPLOAD_SOURCE_EXISTING",
    "UPLOAD_SOURCE_NEW",
    "YOUTUBE_VIDEO_URL_PREFIX",
    "CompleteCollectionStrategy",
    "DedupSearch",
    "PreflightChecker",
    "ResumableUploader",
    "YouTubeAutoUploader",
]


def _authenticated_channel_id(youtube) -> str:
    response = execute_youtube_request(
        youtube.channels().list(part="id", mine=True),
        "channels.list(mine=True) failed",
    )
    try:
        items = validate_youtube_response_items(response, "channels.list(mine=True)")
    except ValidationError as error:
        raise YouTubeAPIError(str(error)) from error
    if not items:
        raise YouTubeAPIError("authenticated user has no YouTube channel")
    item = items[0]
    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
        raise YouTubeAPIError("channels.list(mine=True) returned an invalid channel item")
    return item["id"]


def _verify_upload_channel_id(expected_channel_id: str, authenticated_channel_id: str) -> None:
    if expected_channel_id and expected_channel_id != authenticated_channel_id:
        raise ConfigError(
            "channel_id mismatch: ローカル config と認証済みチャンネルが一致しません。\n"
            f"  config/channel/meta.json (channel.channel_id): {expected_channel_id}\n"
            f"  authenticated channel (channels().list mine=True): {authenticated_channel_id}\n"
            "→ 別チャンネルへの誤投稿を防ぐためアップロードを中止しました。\n"
            "  auth/token.json を削除して対象チャンネルで再認証するか、"
            "meta.json の channel.channel_id を確認してください"
        )


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


def _build_upload_body(metadata: Dict) -> Dict:
    """Validate metadata and build the upload request with publication safeguards."""
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
    elif status_body["privacyStatus"] == "public":
        status_body["privacyStatus"] = "private"
        logger.warning(
            "即時公開を抑止して非公開でアップロードします。"
            "公開する場合は schedule_config.json で予約公開を設定するか、"
            "アップロード後に YouTube Studio で手動公開してください"
        )

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

    return body


class YouTubeAutoUploader(ResumableUploader):
    """YouTube自動アップロードメインクラス

    YouTubeUploadCore を継承し、コレクション単位のアップロード機能を提供する。
    コアのアップロード・サムネイル・リトライロジックは YouTubeUploadCore に委譲。
    責務別のロジック（dedup collaborator / preflight / CC 経路）へ委譲する。
    """

    def __init__(
        self,
        collections_root: Optional[str] = None,
        youtube_clients: YouTubeClients | None = None,
        dedup_search: DedupSearch | None = None,
        preflight_checker: PreflightChecker | None = None,
        complete_collection_strategy: CompleteCollectionStrategy | None = None,
    ) -> None:
        """
        初期化

        Args:
            collections_root (str): collections/ ディレクトリのパス
        """
        super().__init__(youtube_clients)

        if collections_root is None:
            collections_root = channel_dir() / "collections"

        self.collections_root = Path(collections_root)
        self._dedup_search = dedup_search
        self.preflight_checker = (
            preflight_checker if preflight_checker is not None else PreflightChecker(self.collections_root)
        )
        self._complete_collection_strategy = complete_collection_strategy
        self._verified_authenticated_channel_id: str | None = None

    @property
    def dedup_search(self) -> DedupSearch:
        """注入済み helper、または認証後に生成した既定 helper を返す。"""
        if self._dedup_search is None:
            self._ensure_service()
            self._dedup_search = DedupSearch(self.youtube)
        return self._dedup_search

    def _verify_authenticated_upload_channel(self) -> None:
        """OAuth の実チャンネルを config と照合し、同一実行内で結果を保持する。"""
        if self._verified_authenticated_channel_id is not None:
            return
        self._ensure_service()
        authenticated_channel_id = _authenticated_channel_id(self.youtube)
        _verify_upload_channel_id(load_config().meta.channel_id, authenticated_channel_id)
        self._verified_authenticated_channel_id = authenticated_channel_id

    def preflight_check(self, collection_dir: Path) -> None:
        """collection 骨格・チャンネル本人性・メタデータ品質を検証する。"""
        ensure_collection_preflight(collection_dir)
        self._verify_authenticated_upload_channel()
        self.preflight_checker.check(collection_dir)

    def _upload_complete_collection(
        self,
        collection_dir: Path,
        metadata_gen: BAHMetadataGenerator,
        publish_at: Optional[str] = None,
        *,
        resume_session_uri: Optional[str] = None,
        on_session_uri_changed: Optional[Callable[[Optional[str]], None]] = None,
        on_upload_complete: Optional[Callable[[], None]] = None,
    ) -> Optional[Dict]:
        """Complete Collection strategy へ明示的に委譲する。"""
        strategy = (
            self._complete_collection_strategy
            if self._complete_collection_strategy is not None
            else CompleteCollectionStrategy(self.upload_video, self.dedup_search)
        )
        return strategy.upload(
            collection_dir,
            metadata_gen,
            publish_at,
            resume_session_uri=resume_session_uri,
            on_session_uri_changed=on_session_uri_changed,
            on_upload_complete=on_upload_complete,
        )

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
        body = _build_upload_body(metadata)

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
        self.preflight_check(collection_dir)

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
