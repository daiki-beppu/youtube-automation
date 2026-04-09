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
"""

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import schedule  # noqa: E402

logger = logging.getLogger(__name__)


from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader  # noqa: E402
from youtube_automation.utils.channel_config import ChannelConfig  # noqa: E402
from youtube_automation.utils.youtube_service import get_youtube  # noqa: E402


class CollectionUploader:
    """Collection Uploader — CC アップロード専用

    Complete Collection を YouTube にアップロードし、
    publishAt によるスケジュール公開を管理する。
    """

    def __init__(self, collections_root: str = None, config_path: str = None):
        if collections_root is None:
            from youtube_automation.utils.channel_config import ChannelConfig
            collections_root = ChannelConfig.channel_dir() / 'collections'

        if config_path is None:
            config_path = ChannelConfig.channel_dir() / 'config' / 'schedule_config.json'

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
            "upload_settings": {"privacy_status": "public", "category_id": "10"},
            "collections_management": {"auto_move_to_live": True},
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
            self.youtube_service = get_youtube()

    # ─── スケジュール公開 ─────────────────────────────

    # 曜日名 → isoweekday() マッピング（月=1, 日=7）
    _WEEKDAY_MAP = {
        'mon': 1, 'tue': 2, 'wed': 3, 'thu': 4,
        'fri': 5, 'sat': 6, 'sun': 7,
    }

    def _calculate_publish_at(self) -> str | None:
        """CC のスケジュール公開日時を計算

        auto_schedule_enabled が true の場合:
        - cadence で指定された曜日（例: tue, thu, sat）に限定
        - 当日の publish_time を過ぎていたら次の cadence 曜日から探索
        - 同日に既存の公開/予約動画があればさらに次の cadence 曜日にスライド

        auto_schedule_enabled が false の場合は None（即時公開）。

        Returns:
            ISO 8601 形式の公開日時文字列。即時公開時は None。
        """
        schedule_cfg = self.config.get('schedule', {})
        if not schedule_cfg.get('auto_schedule_enabled', False):
            return None

        tz_name = schedule_cfg.get('timezone', 'Asia/Tokyo')
        publish_time = schedule_cfg.get('publish_time', schedule_cfg.get('day1_time', '17:00'))
        tz = ZoneInfo(tz_name)
        hour, minute = map(int, publish_time.split(':'))

        # cadence 曜日を isoweekday に変換（未設定なら全曜日許可）
        cadence = schedule_cfg.get('cadence', [])
        allowed_weekdays = {self._WEEKDAY_MAP[d.lower()] for d in cadence} if cadence else set(range(1, 8))

        now = datetime.now(tz)
        publish_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # 既に今日の公開時刻を過ぎていたら翌日から開始
        if publish_dt <= now:
            publish_dt += timedelta(days=1)

        # cadence 曜日かつ既存公開日と重複しない日を探す
        existing_dates = self._get_published_dates()
        max_slide = 30  # 無限ループ防止
        for _ in range(max_slide):
            if publish_dt.isoweekday() in allowed_weekdays and publish_dt.date() not in existing_dates:
                break
            publish_dt += timedelta(days=1)
            if publish_dt.isoweekday() not in allowed_weekdays:
                continue
            logger.info(f"📅 公開日スライド → {publish_dt.date()} ({publish_dt.strftime('%a')})")

        logger.info(f"📅 CC 公開予定: {publish_dt.isoformat()}")
        return publish_dt.isoformat()

    def _get_published_dates(self) -> set:
        """YouTube API でチャンネルの公開済み/予約済み動画の公開日セットを取得

        search().list() で動画IDを取得し、videos().list(part='status,snippet') で
        公開予約日時（status.publishAt）と公開日時（snippet.publishedAt）の両方を収集する。
        """
        if not self.youtube_service:
            self.initialize_youtube_service()

        tz_name = self.config.get('schedule', {}).get('timezone', 'Asia/Tokyo')
        tz = ZoneInfo(tz_name)
        dates = set()

        try:
            # 動画IDを取得（part='id' でクォータ節約）
            response = self.youtube_service.search().list(
                forMine=True, type='video', order='date', maxResults=50, part='id'
            ).execute()

            video_ids = [item['id']['videoId'] for item in response.get('items', [])]
            if not video_ids:
                return dates

            # status.publishAt（公開予約）と snippet.publishedAt（公開済み）を取得
            videos_response = self.youtube_service.videos().list(
                id=','.join(video_ids), part='status,snippet'
            ).execute()

            for video in videos_response.get('items', []):
                # 公開予約日時を優先、なければ公開日時を使用
                publish_at = video.get('status', {}).get('publishAt')
                if publish_at:
                    dt = datetime.fromisoformat(publish_at.replace('Z', '+00:00'))
                else:
                    dt = datetime.fromisoformat(video['snippet']['publishedAt'].replace('Z', '+00:00'))
                dates.add(dt.astimezone(tz).date())

        except Exception as e:
            logger.warning(f"⚠️  公開日一覧取得エラー: {e}")

        return dates

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
            cc = tracking.get('complete_collection', {})
            logger.info("✅ このコレクションは既にアップロード完了済みです")
            if cc.get('video_url'):
                logger.info(f"📹 {cc['video_url']}")
            if cc.get('upload_time'):
                logger.info(f"📅 アップロード日時: {cc['upload_time']}")
            if cc.get('publish_at'):
                logger.info(f"📅 公開予約: {cc['publish_at']}")
            return {"action": "already_completed", "details": cc}

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

                # プレイリスト自動追加
                self._assign_to_playlists(complete_video['video_id'], collection_path)

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

    # ─── プレイリスト連携 ─────────────────────────────

    def _assign_to_playlists(self, video_id: str, collection_path: Path):
        """アップロード後にプレイリストへ自動追加（失敗してもアップロードはブロックしない）"""
        try:
            from playlist_manager import PlaylistManager

            ws_path = collection_path / 'workflow-state.json'
            if not ws_path.exists():
                return

            with open(ws_path, 'r', encoding='utf-8') as f:
                ws = json.load(f)

            theme = ws.get('theme', '')
            if not theme:
                return

            config = ChannelConfig.load()
            if not config.playlists:
                return

            pm = PlaylistManager()
            assigned = pm.assign_video(video_id, theme)
            if assigned:
                logger.info(f"📋 プレイリスト追加: {assigned}")
        except Exception as e:
            logger.warning(f"⚠️  プレイリスト追加エラー（非致命的）: {e}")

    # ─── ステータス表示 ──────────────────────────────

    def show_status(self, collection_path: Path):
        """進捗表示"""
        tracking = self._load_tracking(collection_path)
        if tracking is None:
            print(f"📋 {collection_path.name}")
            print("   tracking 未初期化 — 実行するとアップロードを開始します")
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
        elif args.status:
            target = uploader._find_collection(args.collection)
            if target:
                uploader.show_status(target)
        elif args.plan:
            target = uploader._find_collection(args.collection)
            if target:
                uploader.show_plan(target)
        else:
            target = uploader._find_collection(args.collection)
            if target:
                uploader.execute_next_step(target)

    except KeyboardInterrupt:
        print("\n🛑 処理が中断されました")
    except Exception as e:
        print(f"❌ エラー: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
