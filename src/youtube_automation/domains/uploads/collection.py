"""Complete Collection upload orchestration owned by the uploads domain."""

import json
import logging
from datetime import datetime
from pathlib import Path

import schedule

from youtube_automation.configuration import channel_dir, load_config
from youtube_automation.domains.uploads._complete_collection_executor import CompleteCollectionExecutorMixin
from youtube_automation.domains.uploads._playlist_assignment import PlaylistAssignmentMixin
from youtube_automation.domains.uploads._published_dates import PublishedDatesMixin
from youtube_automation.domains.uploads._tracking_io import TrackingIOMixin
from youtube_automation.domains.uploads.preflight import ensure_collection_preflight
from youtube_automation.domains.uploads.youtube import YouTubeAutoUploader
from youtube_automation.infrastructure.errors import ValidationError
from youtube_automation.infrastructure.filesystem import (
    list_directory,
    make_directory,
    path_exists,
    path_is_directory,
    read_file_text,
    read_json,
    rename_path,
)
from youtube_automation.infrastructure.google.youtube import YouTubeClients
from youtube_automation.utils.collection_paths import CollectionPaths

logger = logging.getLogger(__name__)

__all__ = ["CollectionUploader"]


class CollectionUploader(
    CompleteCollectionExecutorMixin,
    PlaylistAssignmentMixin,
    PublishedDatesMixin,
    TrackingIOMixin,
):
    """Collection Uploader — CC アップロード専用

    Complete Collection を YouTube にアップロードし、
    publishAt によるスケジュール公開を管理する。

    責務別の挙動は mixin に分離されている（Issue #465）:
    - tracking I/O           : ``TrackingIOMixin``
    - 公開日 / publishAt 計算: ``PublishedDatesMixin``
    - プレイリスト割り当て    : ``PlaylistAssignmentMixin``
    - CC 実行ループ           : ``CompleteCollectionExecutorMixin``
    """

    def __init__(
        self,
        collections_root: str | None = None,
        config_path: str | None = None,
        youtube_clients: YouTubeClients | None = None,
    ):
        if collections_root is None:
            collections_root = channel_dir() / "collections"

        if config_path is None:
            config_path = channel_dir() / "config" / "schedule_config.json"

        self.collections_root = Path(collections_root)
        self.config_path = Path(config_path)
        self.uploader = YouTubeAutoUploader(str(collections_root), youtube_clients)
        self.config = self._load_config()
        self.youtube_service = None
        self.youtube_clients = youtube_clients

    # ─── 設定・初期化 ───────────────────────────────

    def _load_config(self) -> dict:
        """スケジュール設定読み込み"""
        default_config = {
            "schedule": {"day1_time": "10:00", "timezone": "Asia/Tokyo"},
            "upload_settings": {"category_id": "10"},
            "collections_management": {"auto_move_to_live": True},
            "api_limits": {"upload_quota_per_day": 6, "concurrent_uploads": 1, "delay_between_uploads": 5},
        }

        if path_exists(self.config_path):
            try:
                loaded_config = json.loads(read_file_text(self.config_path))
                upload_settings = loaded_config.get("upload_settings")
                if isinstance(upload_settings, dict) and upload_settings.get("privacy_status") is not None:
                    logger.warning(
                        "⚠️  schedule_config.json の upload_settings.privacy_status は参照されません。"
                        "実効値は config/channel/youtube.json::privacy_status です (#1472)"
                    )
                for key, val in loaded_config.items():
                    if isinstance(val, dict) and key in default_config:
                        default_config[key].update(val)
                    else:
                        default_config[key] = val
                return default_config
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"⚠️  設定ファイル読み込みエラー: {e}")
                logger.warning("デフォルト設定を使用します")

        return default_config

    def initialize_youtube_service(self):
        """YouTube API サービス初期化"""
        if self.youtube_clients is None:
            raise TypeError("youtube_clients is required")
        if not self.youtube_service:
            self.youtube_service = self.youtube_clients.youtube

    # ─── コレクション検索 ───────────────────────────

    def find_collections(self, stages: tuple[str, ...] = ("planning", "live")) -> list[Path]:
        """コレクションを検索（指定ステージを探索）"""
        collections = []
        for stage in stages:
            stage_dir = self.collections_root / stage
            if path_exists(stage_dir):
                collections.extend(
                    d for d in list_directory(stage_dir) if path_is_directory(d) and not d.name.startswith(".")
                )
        collections.sort(key=lambda x: x.name)
        return collections

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
        for collection in self.find_collections(("planning",)):
            state_path = CollectionPaths(collection).workflow_state_path
            try:
                state = read_json(state_path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                logger.warning(f"⚠️  workflow-state.json を読み取れないため候補から除外します: {state_path}: {exc}")
                continue

            upload = state.get("upload") if isinstance(state, dict) else None
            if (
                isinstance(state, dict)
                and state.get("phase") == "mastered"
                and isinstance(upload, dict)
                and "video_id" in upload
                and upload["video_id"] is None
            ):
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
        # tracking 読み込み or 初期化
        tracking = self._load_tracking(collection_path)
        if tracking is None:
            tracking = self._initialize_tracking(collection_path)
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
            publish_at = self._calculate_publish_at()
            return self._execute_complete_collection(collection_path, tracking, publish_at=publish_at)

        # 全完了
        tracking["status"] = "completed"
        self._save_tracking(collection_path, tracking)
        logger.info("✅ 全ステップ完了")
        return {"action": "all_completed", "details": {}}

    def ensure_upload_preflight(self, collection_path: Path) -> None:
        """CLI の各入口で共通の骨格・タイトル preflight を実行する。"""
        ensure_collection_preflight(collection_path)
        self.uploader.preflight_check(collection_path)

    # ─── ステータス表示 ──────────────────────────────

    def show_status(self, collection_path: Path):
        """進捗表示"""
        tracking = self._load_tracking(collection_path)
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
        publish_at = self._calculate_publish_at()
        schedule_cfg = self.config.get("schedule", {})

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
            privacy_label = {"public": "即時公開", "unlisted": "限定公開", "private": "非公開"}.get(
                privacy_status, privacy_status
            )
            print(f"  📅 公開設定: {privacy_label} ({privacy_status})")
            if privacy_status != "public":
                print("     └ config/channel/youtube.json::privacy_status を反映")
            looks_like_schedule_intent = any(schedule_cfg.get(k) for k in ("cadence", "publish_time", "day1_time"))
            if looks_like_schedule_intent and schedule_cfg.get("auto_schedule_enabled") is False:
                print(
                    "  ⚠️  schedule.auto_schedule_enabled が false に設定されています。"
                    "予約投稿したい場合は true に変更してください"
                )
        print()
        # 実測クォータ: 約84ユニット/アップロード
        # CC アップロード (84) + 公開日一覧 search (100) + dedup 直前 search (100)
        estimated_quota = 84 + 100 + 100
        print(f"  推定クォータ消費: 約 {estimated_quota:,}/10,000 ユニット")

    # ─── コレクション管理 ────────────────────────────

    def _move_collection_to_live(self, collection_path: Path) -> Path:
        """コレクションを live に移動。移動後のパスを返す"""
        try:
            live_dir = self.collections_root / "live"
            make_directory(live_dir, exist_ok=True)

            new_path = live_dir / collection_path.name

            rename_path(collection_path, new_path)

            logger.info(f"📁 コレクション移動完了: {collection_path.parent.name}/ → live/")
            logger.info(f"   移動先: {new_path}")
            return new_path
        except OSError as e:
            logger.warning(f"⚠️  コレクション移動エラー: {e}")
            return collection_path

    # ─── デーモン ────────────────────────────────────

    def run_automated_schedule(self):
        """自動スケジュール実行（常駐プロセス）"""
        config = load_config()
        logger.info(f"🤖 {config.meta.channel_name} - Collection Uploader 開始")
        logger.info(f"⏰ 投稿時間: {self.config['schedule']['day1_time']}")

        schedule.every().day.at(self.config["schedule"]["day1_time"]).do(self._daily_check_and_upload)

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
        except ValidationError as exc:
            logger.error(f"❌ 日次アップロードを実行しません: {exc}")
            return

        self.execute_next_step(target_collection)

    # ─── 手動実行 ────────────────────────────────────

    def manual_run_next(self, collection_name: str | None = None):
        """手動: 次ステップ実行"""
        target = self.find_collection(collection_name)
        if target:
            self.execute_next_step(target)
