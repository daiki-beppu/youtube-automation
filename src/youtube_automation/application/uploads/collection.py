"""Complete Collection upload orchestration owned by the application layer."""

import logging
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import schedule

from youtube_automation.application.uploads._complete_collection_executor import CompleteCollectionExecutor
from youtube_automation.application.uploads.preflight import PreflightChecker
from youtube_automation.application.uploads.youtube import YouTubeAutoUploader
from youtube_automation.configuration import ScheduleConfig, load_config
from youtube_automation.configuration.loader import load_schedule_config_from_file
from youtube_automation.core.channel_context import channel_dir
from youtube_automation.core.errors import ValidationError, WorkflowStateError
from youtube_automation.domains.collections.inventory import UnreadableWorkflowState, iter_collections
from youtube_automation.domains.collections.workflow_state import Stage
from youtube_automation.domains.uploads._collection_uploader_constants import (
    ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED,
    ACTION_COMPLETE_COLLECTION_UPLOADED,
)
from youtube_automation.domains.uploads._plan_display import print_collection_plan
from youtube_automation.domains.uploads._playlist_assignment import PlaylistAssignment
from youtube_automation.domains.uploads._published_dates import PublishedDatesScheduler
from youtube_automation.domains.uploads._tracking_io import TrackingStore
from youtube_automation.domains.uploads.upload_journal import UploadJournal
from youtube_automation.infrastructure.filesystem import (
    make_directory,
    path_exists,
    path_is_directory,
    rename_path,
)
from youtube_automation.infrastructure.google.youtube import YouTubeClients

logger = logging.getLogger("youtube_automation.domains.uploads.collection")

__all__ = [
    "ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED",
    "ACTION_COMPLETE_COLLECTION_UPLOADED",
    "CollectionUploader",
    "CompleteCollectionExecutor",
    "PlaylistAssignment",
    "PublishedDatesScheduler",
    "TrackingStore",
]


def _create_collection_uploader(
    collections_root: str | Path,
    youtube_clients: YouTubeClients | None,
    *,
    allow_duration_outside_target: bool,
) -> YouTubeAutoUploader:
    """Compose the uploader with the collection-specific preflight policy."""
    return YouTubeAutoUploader(
        str(collections_root),
        youtube_clients,
        preflight_checker=PreflightChecker(
            Path(collections_root),
            allow_duration_outside_target=allow_duration_outside_target,
        ),
    )


def _find_automatic_collection(channel_root: Path) -> Path:
    """Select the single mastered, unpublished collection eligible for automatic upload."""
    candidates = []
    for record in iter_collections(channel_root, ("planning",)):
        collection = record.directory
        if isinstance(record.state, UnreadableWorkflowState):
            logger.warning(
                "⚠️  workflow-state.json を読み取れないため候補から除外します: %s: %s",
                record.state.path,
                record.state.reason,
            )
            continue
        state = record.state

        upload = state.upload
        if state.phase == "mastered" and upload is not None and "video_id" in upload and upload.video_id is None:
            candidates.append(collection)

    if not candidates:
        raise ValidationError(
            "自動選択できる対象コレクションがありません。"
            "planning/ 配下で phase=mastered かつ upload.video_id=null のコレクションを用意するか、"
            "-c で対象を明示してください"
        )
    if len(candidates) > 1:
        names = ", ".join(collection.name for collection in candidates)
        raise ValidationError(f"自動選択対象が複数あります: {names}。-c で対象を明示してください")
    return candidates[0]


def _run_upload_schedule(publish_time: str, check_and_upload: Callable[[], None]) -> None:
    """自動スケジュール実行（常駐プロセス）"""
    config = load_config()
    logger.info(f"🤖 {config.meta.channel_name} - Collection Uploader 開始")
    logger.info(f"⏰ 投稿時間: {publish_time}")

    schedule.every().day.at(publish_time).do(check_and_upload)

    logger.info("🔄 スケジューラー開始（Ctrl+C で終了）")

    try:
        while True:
            schedule.run_pending()
            import time

            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("🛑 スケジューラー停止")


def _check_and_upload(find_collection: Callable[[], Path | None], execute_next_step: Callable[[Path], dict]) -> None:
    """毎日の自動チェック・アップロード処理"""
    logger.info(f"📅 日次チェック実行: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        target_collection = find_collection()
    except (ValidationError, WorkflowStateError) as exc:
        logger.error(f"❌ 日次アップロードを実行しません: {exc}")
        return

    execute_next_step(target_collection)


def _upload_details(record: dict, fields: tuple[tuple[str, str], ...]) -> Iterator[str]:
    """Format available upload details for status output and completion logs."""
    for key, label in fields:
        if value := record.get(key):
            yield f"{label}{value}"


class CollectionUploader:
    """Collection Uploader — CC アップロード専用

    Complete Collection を YouTube にアップロードし、
    publishAt によるスケジュール公開を管理する。

    責務別の挙動は collaborator へ委譲する:
    - tracking I/O           : ``TrackingStore`` への委譲
    - 公開日 / publishAt 計算: ``PublishedDatesScheduler`` への委譲
    - プレイリスト割り当て    : ``PlaylistAssignment`` への委譲
    - CC 実行ループ           : ``CompleteCollectionExecutor``
    """

    def __init__(
        self,
        collections_root: str | None = None,
        config_path: str | None = None,
        youtube_clients: YouTubeClients | None = None,
        tracking_store: TrackingStore | None = None,
        published_dates: PublishedDatesScheduler | None = None,
        playlist_assignment: PlaylistAssignment | None = None,
        complete_collection_executor: CompleteCollectionExecutor | None = None,
        upload_journal_factory: Callable[[Path], UploadJournal] = UploadJournal,
        allow_duration_outside_target: bool = False,
    ):
        if collections_root is None:
            collections_root = channel_dir() / "collections"

        if config_path is None:
            config_path = channel_dir() / "config" / "schedule_config.json"

        self.collections_root = Path(collections_root)
        self.config_path = Path(config_path)
        self.uploader = _create_collection_uploader(
            collections_root,
            youtube_clients,
            allow_duration_outside_target=allow_duration_outside_target,
        )
        self.config = load_schedule_config_from_file(self.config_path)
        self.tracking_store = tracking_store or TrackingStore(self.collections_root, self.config)
        self.upload_journal_factory = upload_journal_factory
        self.youtube_service = None
        self.youtube_clients = youtube_clients
        self.published_dates = published_dates or PublishedDatesScheduler(self.config, self._provide_youtube_service)
        self.playlist_assignment = (
            playlist_assignment if playlist_assignment is not None else PlaylistAssignment(youtube_clients)
        )
        self.complete_collection_executor = (
            complete_collection_executor
            if complete_collection_executor is not None
            else CompleteCollectionExecutor(
                self.uploader,
                self.tracking_store,
                self.config,
                self.playlist_assignment,
                self._move_collection_to_live,
                upload_journal_factory,
            )
        )

    # ─── 設定・初期化 ───────────────────────────────

    def _apply_config(self, config: ScheduleConfig) -> None:
        """解決済み設定を差し替え、同じ設定を参照する collaborator へ一括反映する。

        ``ScheduleConfig`` は frozen なため差し替えは新インスタンスになる。
        collaborator は構築時に受け取った参照を保持するので、ここで同期しないと
        古い設定を読み続ける。
        """
        self.config = config
        self.tracking_store.config = config
        self.published_dates.config = config
        self.complete_collection_executor.config = config

    def initialize_youtube_service(self):
        """YouTube API サービス初期化"""
        if self.youtube_clients is None:
            raise TypeError("youtube_clients is required")
        if not self.youtube_service:
            self.youtube_service = self.youtube_clients.youtube

    def _provide_youtube_service(self) -> object:
        self.initialize_youtube_service()
        return self.youtube_service

    # ─── コレクション検索 ───────────────────────────

    def find_collections(self, stages: tuple[Stage, ...] = ("planning", "live")) -> list[Path]:
        """コレクションを検索（指定ステージを探索）"""
        # unreadable も明示名検索では従来どおり候補に残す。
        return [record.directory for record in iter_collections(self.collections_root.parent, stages)]

    def find_collection(self, collection_name: str | None = None) -> Path | None:
        """名前指定なら全ステージ、未指定なら未公開の planning コレクションを検索する。"""
        all_collections = self.find_collections()
        if collection_name:
            for col in all_collections:
                if collection_name in col.name:
                    return col
            logger.error(f"❌ コレクションが見つかりません: {collection_name}")
            return None

        return _find_automatic_collection(self.collections_root.parent)

    # ─── コアオーケストレーション ────────────────────

    def execute_next_step(self, collection_path: Path) -> dict:
        """次の投稿ステップを自動判定・実行

        CC アップロード → live 移動 → 完了

        Returns:
            dict: {"action": str, "details": dict}
        """
        journal_status = self.upload_journal_factory(collection_path).status("complete_collection")
        if journal_status.is_corrupt:
            logger.error("❌ upload journal 破損のため upload 可否を判定できません")
            return {
                "action": "complete_collection_failed",
                "details": {"error": "upload journal is corrupt", "quarantine": str(journal_status.quarantine_path)},
            }
        # tracking 読み込み or 初期化
        tracking = self.tracking_store.load(collection_path)
        if tracking is None:
            tracking = self.tracking_store.initialize(collection_path)
            logger.info("📋 tracking 初期化完了")

        # 既に完了
        if tracking.get("status") == "completed":
            cc = tracking.get("complete_collection", {})
            logger.info("✅ このコレクションは既にアップロード完了済みです")
            for detail in _upload_details(
                cc,
                (("video_url", "📹 "), ("upload_time", "📅 アップロード日時: "), ("publish_at", "📅 公開予約: ")),
            ):
                logger.info(detail)
            return {"action": "already_completed", "details": cc}

        # Complete Collection アップロード
        cc = tracking.get("complete_collection", {})
        if cc.get("status") != "completed":
            publish_at = self.published_dates.calculate_publish_at()
            return self._execute_complete_collection(collection_path, tracking, publish_at=publish_at)

        # 全完了
        tracking["status"] = "completed"
        self.tracking_store.save(collection_path, tracking)
        logger.info("✅ 全ステップ完了")
        return {"action": "all_completed", "details": {}}

    def _execute_complete_collection(
        self,
        collection_path: Path,
        tracking: dict,
        publish_at: str | None = None,
    ) -> dict:
        return self.complete_collection_executor.run(collection_path, tracking, publish_at)

    def preflight_check(self, collection_path: Path) -> None:
        """アップロードを伴わない経路（``--plan``）から upload 境界の preflight を依頼する。

        検査の実体は `YouTubeAutoUploader.preflight_check` が単独で持ち、
        `execute_next_step` 経路では `upload_collection` の内部で同じ検査集合が
        1 回だけ走る。ここで検査を再実装しないことが二重実行を防ぐ条件。
        """
        self.uploader.preflight_check(collection_path)

    # ─── ステータス表示 ──────────────────────────────

    def show_status(self, collection_path: Path):
        """進捗表示"""
        tracking = self.tracking_store.load(collection_path)
        if tracking is None:
            print(f"📋 {collection_path.name}")
            print("   tracking 未初期化 — 実行するとアップロードを開始します")
            return

        cc = tracking.get("complete_collection", {})

        print(f"📋 {tracking['collection_name']}")

        cc_status = "✅" if cc.get("status") == "completed" else ("❌" if cc.get("status") == "failed" else "⏳")
        cc_date = ""
        if cc.get("upload_time"):
            cc_date = f" ({cc['upload_time'][:10]})"
        print(f"  Complete Collection{cc_date}: {cc_status}")

        for detail in _upload_details(cc, (("video_url", "  📹 "), ("publish_at", "  📅 公開予定: "))):
            print(detail)

        overall = "完了" if tracking.get("status") == "completed" else "未完了"
        print(f"  Status: {overall}")

    def show_plan(self, collection_path: Path):
        """ドライラン — スケジュール計算のみ表示"""
        publish_at = self.published_dates.calculate_publish_at()
        privacy_status = "" if publish_at else load_config().youtube.api.privacy_status
        print_collection_plan(
            collection_path,
            publish_at,
            privacy_status,
            scheduling_disabled=self.config.scheduling_explicitly_disabled,
        )

    # ─── コレクション管理 ────────────────────────────

    def _move_collection_to_live(self, collection_path: Path) -> Path:
        """コレクションを live に移動。移動後のパスを返す"""
        live_dir = self.collections_root / "live"
        new_path = live_dir / collection_path.name
        try:
            make_directory(live_dir, exist_ok=True)
            rename_path(collection_path, new_path)
        except OSError as e:
            if path_exists(collection_path) or not path_is_directory(new_path):
                logger.warning(f"⚠️  コレクション移動エラー: {e}")
                return collection_path

        logger.info(f"📁 コレクション移動完了: {collection_path.parent.name}/ → live/")
        logger.info(f"   移動先: {new_path}")
        return new_path

    # ─── デーモン ────────────────────────────────────

    def run_automated_schedule(self):
        _run_upload_schedule(self.config.publish_time, self._daily_check_and_upload)

    def _daily_check_and_upload(self):
        _check_and_upload(self.find_collection, self.execute_next_step)

    # ─── 手動実行 ────────────────────────────────────

    def manual_run_next(self, collection_name: str | None = None):
        """手動: 次ステップ実行"""
        target = self.find_collection(collection_name)
        if target:
            self.execute_next_step(target)
