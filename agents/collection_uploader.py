#!/usr/bin/env python3
"""
8-Bit Adventure Hub (8BAH) - Collection Uploader

Complete Collection を YouTube にアップロードし、
publishAt によるスケジュール公開（private → public）を管理する。

Features:
- Complete Collection アップロード
- スマートスケジュール公開（最終公開日+1日）
- トラッキングによるリジューム対応
- collections/ ディレクトリ自動管理（planning → live）
"""

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import schedule  # noqa: E402

logger = logging.getLogger(__name__)

# プロジェクトルートをパスに追加
sys.path.append(str(Path(__file__).parent.parent))

from agents.youtube_auto_uploader import YouTubeAutoUploader  # noqa: E402
from auth.oauth_handler import YouTubeOAuthHandler  # noqa: E402
from utils.channel_config import ChannelConfig  # noqa: E402


class CollectionUploader:
    """Collection Uploader — CC アップロード専用

    Complete Collection を YouTube にアップロードし、
    publishAt によるスケジュール公開を管理する。
    """

    def __init__(self, collections_root: str = None, config_path: str = None):
        if collections_root is None:
            from utils.channel_config import ChannelConfig
            collections_root = ChannelConfig.channel_dir() / 'collections'

        if config_path is None:
            config_path = Path(__file__).parent.parent / 'config' / 'schedule_config.json'

        self.collections_root = Path(collections_root)
        self.config_path = Path(config_path)
        self.uploader = YouTubeAutoUploader(str(collections_root))
        self.auth_handler = YouTubeOAuthHandler()
        self.config = self._load_config()
        self.youtube_service = None

    # ─── 設定・初期化 ───────────────────────────────

    def _load_config(self) -> dict:
        """スケジュール設定読み込み"""
        default_config = {
            "schedule": {"day1_time": "10:00", "timezone": "Asia/Tokyo"},
            "upload_settings": {"privacy_status": "public", "category_id": "10"},
            "collections_management": {"auto_move_to_live": True, "backup_before_move": False},
            "api_limits": {"upload_quota_per_day": 6, "concurrent_uploads": 1, "delay_between_uploads": 5},
        }

        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
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
            self.youtube_service = self.auth_handler.get_youtube_service()

    # ─── スケジュール公開 ─────────────────────────────

    def _get_last_published_date(self) -> datetime | None:
        """YouTube API でチャンネル最終公開日を取得

        Returns:
            最終公開動画の公開日時（JST）。失敗時は None。
        """
        if not self.youtube_service:
            self.initialize_youtube_service()

        try:
            response = self.youtube_service.search().list(
                forMine=True, type='video', order='date', maxResults=1, part='snippet'
            ).execute()

            items = response.get('items', [])
            if not items:
                logger.warning("⚠️  公開動画が見つかりません")
                return None

            published_str = items[0]['snippet']['publishedAt']
            published_utc = datetime.fromisoformat(published_str.replace('Z', '+00:00'))
            tz_name = self.config.get('schedule', {}).get('timezone', 'Asia/Tokyo')
            return published_utc.astimezone(ZoneInfo(tz_name))

        except Exception as e:
            logger.warning(f"⚠️  最終公開日取得エラー: {e}")
            return None

    def _calculate_publish_at(self) -> str | None:
        """CC のスケジュール公開日時を計算

        最終公開日の翌日の指定時刻を返す。
        API 失敗時は今日の翌日をフォールバック。
        public 設定時は None（即時公開）。

        Returns:
            ISO 8601 形式の公開日時文字列。public 設定時は None。
        """
        upload_cfg = self.config.get('upload_settings', {})
        if upload_cfg.get('privacy_status') == 'public':
            return None

        schedule_cfg = self.config.get('schedule', {})
        tz_name = schedule_cfg.get('timezone', 'Asia/Tokyo')
        publish_time = schedule_cfg.get('day1_time', '10:00')
        tz = ZoneInfo(tz_name)
        hour, minute = map(int, publish_time.split(':'))

        last_published = self._get_last_published_date()
        if last_published:
            base_date = last_published.date()
            logger.info(f"📅 最終公開日: {base_date}")
        else:
            base_date = datetime.now(tz).date()
            logger.info(f"📅 最終公開日取得失敗 — 今日 ({base_date}) を基準に計算")

        publish_dt = datetime(base_date.year, base_date.month, base_date.day,
                              hour, minute, 0, tzinfo=tz) + timedelta(days=1)

        # 過去日チェック: 公開日が現在より前なら翌日にスライド
        now = datetime.now(tz)
        if publish_dt <= now:
            publish_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=1)
            logger.info("📅 過去日を検出 — 翌日にスライド")

        logger.info(f"📅 CC 公開予定: {publish_dt.isoformat()}")
        return publish_dt.isoformat()

    # ─── コレクション検索 ───────────────────────────

    def find_collections(self, stages: tuple[str, ...] = ('planning', 'live')) -> list[Path]:
        """コレクションを検索（指定ステージを探索）"""
        collections = []
        for stage in stages:
            stage_dir = self.collections_root / stage
            if stage_dir.exists():
                collections.extend(d for d in stage_dir.iterdir() if d.is_dir() and not d.name.startswith('.'))
        collections.sort(key=lambda x: x.name)
        return collections

    def _find_collection(self, collection_name: str = None) -> Path | None:
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

    # ─── Tracking ────────────────────────────────

    def _get_tracking_path(self, collection_path: Path) -> Path:
        return collection_path / '20-documentation' / 'upload_tracking.json'

    def _load_tracking(self, collection_path: Path) -> dict | None:
        """tracking ファイル読み込み"""
        tracking_file = self._get_tracking_path(collection_path)
        if not tracking_file.exists():
            return None

        try:
            with open(tracking_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def _save_tracking(self, collection_path: Path, tracking: dict):
        """tracking 保存"""
        tracking_file = self._get_tracking_path(collection_path)
        tracking_file.parent.mkdir(exist_ok=True)
        try:
            with open(tracking_file, 'w', encoding='utf-8') as f:
                json.dump(tracking, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"⚠️  追跡ファイル保存エラー: {e}")

    def _initialize_tracking(self, collection_path: Path) -> dict:
        """tracking を初期化"""
        tracking = {
            "schema_version": 3,
            "collection_name": collection_path.name,
            "status": "in_progress",
            "complete_collection": {"status": "pending"},
        }

        self._save_tracking(collection_path, tracking)
        return tracking

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
        if tracking.get('status') == 'completed':
            logger.info("✅ このコレクションは既にアップロード完了済みです")
            return {"action": "already_completed", "details": {}}

        # Complete Collection アップロード
        cc = tracking.get('complete_collection', {})
        if cc.get('status') != 'completed':
            publish_at = self._calculate_publish_at()
            return self._execute_complete_collection(collection_path, tracking, publish_at=publish_at)

        # 全完了
        tracking['status'] = 'completed'
        self._save_tracking(collection_path, tracking)
        logger.info("✅ 全ステップ完了")
        return {"action": "all_completed", "details": {}}

    def _execute_complete_collection(self, collection_path: Path, tracking: dict, publish_at: str = None) -> dict:
        """Complete Collection アップロード"""
        logger.info("📅 Complete Collection アップロード開始")
        logger.info(f"🎵 コレクション: {collection_path.name}")
        if publish_at:
            logger.info(f"📅 スケジュール公開: {publish_at}")

        try:
            result = self.uploader.upload_collection(str(collection_path), publish_at=publish_at)
            complete_video = result.get('complete_video')

            if complete_video and 'video_id' in complete_video:
                tracking['complete_collection'] = {
                    'video_id': complete_video['video_id'],
                    'video_url': complete_video['video_url'],
                    'upload_time': datetime.now().isoformat(),
                    'publish_at': publish_at,
                    'status': 'completed',
                }
                tracking['status'] = 'completed'

                # live 移動
                if self.config['collections_management'].get('auto_move_to_live', True):
                    collection_path = self._move_collection_to_live(collection_path)

                self._save_tracking(collection_path, tracking)

                logger.info("✅ Complete Collection アップロード完了")
                logger.info(f"📹 {complete_video['video_url']}")

                return {"action": "complete_collection_uploaded", "details": {**tracking['complete_collection']}}
            else:
                error_msg = (complete_video or {}).get('error', 'Unknown error')
                tracking['complete_collection']['status'] = 'failed'
                tracking['complete_collection']['error'] = error_msg
                self._save_tracking(collection_path, tracking)
                logger.error(f"❌ Complete Collection 失敗: {error_msg}")
                return {"action": "complete_collection_failed", "details": {"error": error_msg}}

        except Exception as e:
            tracking['complete_collection']['status'] = 'failed'
            tracking['complete_collection']['error'] = str(e)
            self._save_tracking(collection_path, tracking)
            logger.error(f"❌ Complete Collection エラー: {e}")
            return {"action": "complete_collection_failed", "details": {"error": str(e)}}

    # ─── ステータス表示 ──────────────────────────────

    def show_status(self, collection_path: Path):
        """進捗表示"""
        tracking = self._load_tracking(collection_path)
        if tracking is None:
            print(f"📋 {collection_path.name}")
            print("   tracking 未初期化 — --next で開始してください")
            return

        cc = tracking.get('complete_collection', {})

        print(f"📋 {tracking['collection_name']}")

        cc_status = "✅" if cc.get('status') == 'completed' else ("❌" if cc.get('status') == 'failed' else "⏳")
        cc_date = ""
        if cc.get('upload_time'):
            cc_date = f" ({cc['upload_time'][:10]})"
        print(f"  Complete Collection{cc_date}: {cc_status}")

        if cc.get('video_url'):
            print(f"  📹 {cc['video_url']}")
        if cc.get('publish_at'):
            print(f"  📅 公開予定: {cc['publish_at']}")

        overall = "完了" if tracking.get('status') == 'completed' else "未完了"
        print(f"  Status: {overall}")

    def show_plan(self, collection_path: Path):
        """ドライラン — スケジュール計算のみ表示"""
        publish_at = self._calculate_publish_at()

        print(f"📋 アップロード計画: {collection_path.name}")
        print()
        print("  ── Complete Collection アップロード ──")
        print("  1. Complete Collection アップロード")
        print("  2. live/ に移動")
        print()
        if publish_at:
            print(f"  📅 公開予定: {publish_at}")
        else:
            print("  📅 公開設定: 即時公開 (public)")
        print()
        # 実測クォータ: 約84ユニット/アップロード
        estimated_quota = 84 + 100  # CC + search API
        print(f"  推定クォータ消費: 約 {estimated_quota:,}/10,000 ユニット")

    # ─── コレクション管理 ────────────────────────────

    def _move_collection_to_live(self, collection_path: Path) -> Path:
        """コレクションを live に移動。移動後のパスを返す"""
        try:
            live_dir = self.collections_root / 'live'
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
        config = ChannelConfig.load()
        logger.info(f"🤖 {config.channel_name} - Collection Uploader 開始")
        logger.info(f"⏰ 投稿時間: {self.config['schedule']['day1_time']}")

        schedule.every().day.at(self.config['schedule']['day1_time']).do(self._daily_check_and_upload)

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

    def manual_run_next(self, collection_name: str = None):
        """手動: 次ステップ実行"""
        target = self._find_collection(collection_name)
        if target:
            self.execute_next_step(target)


def main():
    """メイン関数"""
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    config = ChannelConfig.load()
    parser = argparse.ArgumentParser(description=f'{config.channel_short} Collection Uploader')
    parser.add_argument('--next', action='store_true', help='次ステップ実行')
    parser.add_argument('--status', action='store_true', help='進捗表示')
    parser.add_argument('--plan', action='store_true', help='スケジュール計算（ドライラン）')
    parser.add_argument('--daemon', '-d', action='store_true', help='常駐スケジューラー起動')
    parser.add_argument('--collection', '-c', help='対象コレクション名（部分一致）')
    parser.add_argument('--config', help='設定ファイルパス')

    args = parser.parse_args()

    try:
        uploader = CollectionUploader(config_path=args.config)

        if args.daemon:
            uploader.run_automated_schedule()
        elif args.next:
            target = uploader._find_collection(args.collection)
            if target:
                uploader.execute_next_step(target)
        elif args.status:
            target = uploader._find_collection(args.collection)
            if target:
                uploader.show_status(target)
        elif args.plan:
            target = uploader._find_collection(args.collection)
            if target:
                uploader.show_plan(target)
        else:
            print("使用法:")
            print("  次ステップ実行:     python collection_uploader.py --next [-c NAME]")
            print("  進捗表示:           python collection_uploader.py --status [-c NAME]")
            print("  スケジュール計算:   python collection_uploader.py --plan [-c NAME]")
            print("  常駐スケジューラー: python collection_uploader.py --daemon")

    except KeyboardInterrupt:
        print("\n🛑 処理が中断されました")
    except Exception as e:
        print(f"❌ エラー: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
