#!/usr/bin/env python3
"""
Collection Uploader

Complete Collection を YouTube にアップロードし、
publishAt によるスケジュール公開（private → public）を管理する。

Features:
- Complete Collection アップロード
- スマートスケジュール公開（最終公開日+1日）
- トラッキングによるリジューム対応
- collections/ ディレクトリ自動管理（planning → live）

責務分割（挙動不変・Issue #465）:
- ``_collection_uploader_constants``                   : 共有定数
- ``_tracking_io.TrackingIOMixin``                     : tracking / workflow-state JSON の I/O
- ``_published_dates.PublishedDatesMixin``             : 公開日一覧取得 / publishAt 計算
- ``_playlist_assignment.PlaylistAssignmentMixin``     : プレイリスト自動割り当て
- ``_complete_collection_executor.CompleteCollectionExecutorMixin``  : CC 実行ループ
本モジュールはクラス本体（初期化 / dispatcher / ドライラン / コレクション管理 / デーモン / CLI）を保持する。
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import schedule

logger = logging.getLogger(__name__)


from youtube_automation.agents._collection_uploader_constants import (  # noqa: E402
    ACTION_COMPLETE_COLLECTION_DEDUP_SKIPPED,
    ACTION_COMPLETE_COLLECTION_UPLOADED,
    TRACKING_STATUS_COMPLETED,
    WORKFLOW_PHASE_COMPLETE,
    WORKFLOW_STAGE_LIVE,
)
from youtube_automation.agents._complete_collection_executor import (  # noqa: E402
    CompleteCollectionExecutorMixin,
)
from youtube_automation.agents._playlist_assignment import (  # noqa: E402
    PlaylistAssignmentMixin,
)
from youtube_automation.agents._published_dates import (  # noqa: E402
    PublishedDatesMixin,
    _scheduling_enabled,
)
from youtube_automation.agents._tracking_io import TrackingIOMixin  # noqa: E402
from youtube_automation.agents.youtube_auto_uploader import (  # noqa: E402
    UPLOAD_SOURCE_EXISTING,
    YouTubeAutoUploader,
)
from youtube_automation.scripts.collection_preflight import ensure_collection_preflight  # noqa: E402
from youtube_automation.scripts.playlist_manager import PlaylistManager  # noqa: E402
from youtube_automation.utils.config import channel_dir, load_config  # noqa: E402
from youtube_automation.utils.youtube_service import get_youtube  # noqa: E402

# 後方互換 / 公開 API: 定数・主要シンボルは従来どおり本モジュールから import できるよう再エクスポートする。
# 既存テスト（``patch("youtube_automation.agents.collection_uploader.PlaylistManager")`` 等）に対応するため、
# PlaylistManager / load_config / YouTubeAutoUploader 等もこの位置で import している。
__all__ = [
    "ACTION_COMPLETE_COLLECTION_DEDUP_SKIPPED",
    "ACTION_COMPLETE_COLLECTION_UPLOADED",
    "TRACKING_STATUS_COMPLETED",
    "UPLOAD_SOURCE_EXISTING",
    "WORKFLOW_PHASE_COMPLETE",
    "WORKFLOW_STAGE_LIVE",
    "CollectionUploader",
    "PlaylistManager",
    "YouTubeAutoUploader",
    "_scheduling_enabled",
    "load_config",
    "main",
]


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

    def __init__(self, collections_root: str | None = None, config_path: str | None = None):
        if collections_root is None:
            collections_root = channel_dir() / "collections"

        if config_path is None:
            config_path = channel_dir() / "config" / "schedule_config.json"

        self.collections_root = Path(collections_root)
        self.config_path = Path(config_path)
        self.uploader = YouTubeAutoUploader(str(collections_root))
        self.config = self._load_config()
        self.youtube_service = None

    # ─── 設定・初期化 ───────────────────────────────

    def _load_config(self) -> dict:
        """スケジュール設定読み込み"""
        default_config = {
            "schedule": {"day1_time": "10:00", "timezone": "Asia/Tokyo"},
            "upload_settings": {"category_id": "10"},
            "collections_management": {"auto_move_to_live": True},
            "api_limits": {"upload_quota_per_day": 6, "concurrent_uploads": 1, "delay_between_uploads": 5},
        }

        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded_config = json.load(f)
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
            except Exception as e:
                logger.warning(f"⚠️  設定ファイル読み込みエラー: {e}")
                logger.warning("デフォルト設定を使用します")

        return default_config

    def initialize_youtube_service(self):
        """YouTube API サービス初期化"""
        if not self.youtube_service:
            self.youtube_service = get_youtube()

    # ─── コレクション検索 ───────────────────────────

    def find_collections(self, stages: tuple[str, ...] = ("planning", "live")) -> list[Path]:
        """コレクションを検索（指定ステージを探索）"""
        collections = []
        for stage in stages:
            stage_dir = self.collections_root / stage
            if stage_dir.exists():
                collections.extend(d for d in stage_dir.iterdir() if d.is_dir() and not d.name.startswith("."))
        collections.sort(key=lambda x: x.name)
        return collections

    def _find_collection(self, collection_name: str | None = None) -> Path | None:
        """名前でコレクションを検索（部分一致、planning/ と live/ を探索）"""
        all_collections = self.find_collections()
        if collection_name:
            for col in all_collections:
                if collection_name in col.name:
                    return col
            logger.error(f"❌ コレクションが見つかりません: {collection_name}")
            return None
        if not all_collections:
            logger.error("❌ 対象コレクションが見つかりません")
            return None
        return all_collections[0]

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
            live_dir.mkdir(exist_ok=True)

            new_path = live_dir / collection_path.name

            collection_path.rename(new_path)

            logger.info(f"📁 コレクション移動完了: {collection_path.parent.name}/ → live/")
            logger.info(f"   移動先: {new_path}")
            return new_path
        except Exception as e:
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

        collections = self.find_collections()
        if not collections:
            logger.info("📋 処理対象のコレクションはありません")
            return

        target_collection = collections[0]
        self.execute_next_step(target_collection)

    # ─── 手動実行 ────────────────────────────────────

    def manual_run_next(self, collection_name: str | None = None):
        """手動: 次ステップ実行"""
        target = self._find_collection(collection_name)
        if target:
            self.execute_next_step(target)


def main():
    """メイン関数"""
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    config = load_config()
    parser = argparse.ArgumentParser(description=f"{config.meta.channel_short} Collection Uploader")
    parser.add_argument("--status", action="store_true", help="進捗表示")
    parser.add_argument("--plan", action="store_true", help="スケジュール計算（ドライラン）")
    parser.add_argument("--daemon", "-d", action="store_true", help="常駐スケジューラー起動")
    parser.add_argument("--collection", "-c", help="対象コレクション名（部分一致）")
    parser.add_argument("--config", help="設定ファイルパス")

    args = parser.parse_args()

    try:
        uploader = CollectionUploader(config_path=args.config)

        if args.daemon:
            uploader.run_automated_schedule()
        elif args.status:
            target = uploader._find_collection(args.collection)
            if target:
                uploader.show_status(target)
        elif args.plan:
            target = uploader._find_collection(args.collection)
            if target:
                ensure_collection_preflight(target)
                uploader.show_plan(target)
        else:
            target = uploader._find_collection(args.collection)
            if target:
                ensure_collection_preflight(target)
                uploader.execute_next_step(target)

    except KeyboardInterrupt:
        print("\n🛑 処理が中断されました")
    except Exception as e:
        print(f"❌ エラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
