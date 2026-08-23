"""Complete Collection upload orchestration owned by the uploads domain."""

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import schedule

from youtube_automation.configuration import ScheduleConfig, channel_dir, load_config
from youtube_automation.configuration.loader import load_schedule_config_from_file
from youtube_automation.core.adapters.youtube import (
    DAILY_BUCKET_LIMITS,
    UNIT_COSTS,
    UNIT_POOL_LIMIT,
    complete_collection_quota_plan,
)
from youtube_automation.core.errors import ValidationError, WorkflowStateError
from youtube_automation.domains.collections.inventory import UnreadableWorkflowState, iter_collections
from youtube_automation.domains.collections.workflow_state import Stage
from youtube_automation.domains.uploads._collection_uploader_constants import (
    ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED,
    ACTION_COMPLETE_COLLECTION_UPLOADED,
)
from youtube_automation.domains.uploads._complete_collection_executor import CompleteCollectionExecutor
from youtube_automation.domains.uploads._playlist_assignment import PlaylistAssignment
from youtube_automation.domains.uploads._preflight import PreflightChecker
from youtube_automation.domains.uploads._published_dates import PublishedDatesScheduler
from youtube_automation.domains.uploads._tracking_io import TrackingStore
from youtube_automation.domains.uploads.upload_journal import UploadJournal, UploadJournalOutcome
from youtube_automation.domains.uploads.youtube import YouTubeAutoUploader
from youtube_automation.infrastructure.filesystem import (
    make_directory,
    path_exists,
    path_is_directory,
    rename_path,
)
from youtube_automation.infrastructure.google.youtube import YouTubeClients

logger = logging.getLogger(__name__)

__all__ = [
    "ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED",
    "ACTION_COMPLETE_COLLECTION_UPLOADED",
    "CollectionUploader",
    "CompleteCollectionExecutor",
    "PlaylistAssignment",
    "PublishedDatesScheduler",
    "TrackingStore",
]


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
        self.uploader = YouTubeAutoUploader(
            str(collections_root),
            youtube_clients,
            preflight_checker=PreflightChecker(
                self.collections_root,
                allow_duration_outside_target=allow_duration_outside_target,
            ),
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

        candidates = []
        for record in iter_collections(self.collections_root.parent, ("planning",)):
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

    # ─── コアオーケストレーション ────────────────────

    def execute_next_step(self, collection_path: Path) -> dict:
        """次の投稿ステップを自動判定・実行

        CC アップロード → live 移動 → 完了

        Returns:
            dict: {"action": str, "details": dict}
        """
        journal_status = self.upload_journal_factory(collection_path).status("complete_collection")
        if journal_status.outcome is UploadJournalOutcome.CORRUPT:
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
            if cc.get("video_url"):
                logger.info(f"📹 {cc['video_url']}")
            if cc.get("upload_time"):
                logger.info(f"📅 アップロード日時: {cc['upload_time']}")
            if cc.get("publish_at"):
                logger.info(f"📅 公開予約: {cc['publish_at']}")
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

        if cc.get("video_url"):
            print(f"  📹 {cc['video_url']}")
        if cc.get("publish_at"):
            print(f"  📅 公開予定: {cc['publish_at']}")

        overall = "完了" if tracking.get("status") == "completed" else "未完了"
        print(f"  Status: {overall}")

    def show_plan(self, collection_path: Path):
        """ドライラン — スケジュール計算のみ表示"""
        publish_at = self.published_dates.calculate_publish_at()

        print(f"📋 アップロード計画: {collection_path.name}")
        print()
        print("  ── Complete Collection アップロード ──")
        print("  1. Complete Collection アップロード")
        print("  2. live/ に移動")
        print()
        if publish_at:
            print(f"  📅 公開予定: {publish_at}")
        else:
            privacy_status = load_config().youtube.api.privacy_status
            if privacy_status == "public":
                print("  📅 公開設定: 非公開でアップロード（即時公開は行いません）")
            else:
                privacy_label = {"unlisted": "限定公開", "private": "非公開"}.get(privacy_status, privacy_status)
                print(f"  📅 公開設定: {privacy_label} ({privacy_status})")
                print("     └ config/channel/youtube.json::privacy_status を反映")
            if self.config.scheduling_explicitly_disabled:
                print(
                    "  ⚠️  schedule.auto_schedule_enabled が false に設定されています。"
                    "予約投稿したい場合は true に変更してください"
                )
        print()
        quota_plan = complete_collection_quota_plan()
        print("  推定 YouTube API quota:")
        for method, calls in quota_plan.bucket_calls.items():
            print(f"    独立日次 bucket: {method} {calls}/{DAILY_BUCKET_LIMITS[method]} calls")
        for method, calls in quota_plan.unit_pool_calls.items():
            print(f"    unit pool: {method} {calls} × {UNIT_COSTS[method]} units")
        print(f"    unit pool 合計: {quota_plan.unit_pool_units:,}/{UNIT_POOL_LIMIT:,} units")

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
        """自動スケジュール実行（常駐プロセス）"""
        config = load_config()
        logger.info(f"🤖 {config.meta.channel_name} - Collection Uploader 開始")
        logger.info(f"⏰ 投稿時間: {self.config.publish_time}")

        schedule.every().day.at(self.config.publish_time).do(self._daily_check_and_upload)

        logger.info("🔄 スケジューラー開始（Ctrl+C で終了）")

        try:
            while True:
                schedule.run_pending()
                import time

                time.sleep(60)
        except KeyboardInterrupt:
            logger.info("🛑 スケジューラー停止")

    def _daily_check_and_upload(self):
        """毎日の自動チェック・アップロード処理"""
        logger.info(f"📅 日次チェック実行: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            target_collection = self.find_collection()
        except (ValidationError, WorkflowStateError) as exc:
            logger.error(f"❌ 日次アップロードを実行しません: {exc}")
            return

        self.execute_next_step(target_collection)

    # ─── 手動実行 ────────────────────────────────────

    def manual_run_next(self, collection_name: str | None = None):
        """手動: 次ステップ実行"""
        target = self.find_collection(collection_name)
        if target:
            self.execute_next_step(target)
