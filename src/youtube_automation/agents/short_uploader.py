#!/usr/bin/env python3
"""
Short Uploader — Shorts 動画アップロード専用

CC（Complete Collection）の実際の公開日を基準に翌日の固定時刻で publishAt を算出し、
Shorts 動画を YouTube にアップロードする。アップロード本体は YouTubeAutoUploader に
委譲し、メタデータ生成は BAHMetadataGenerator.generate_shorts_metadata を使う。

Features:
- CC publish_at 基準の公開日計算（upload_tracking.json から取得）
- BAHMetadataGenerator 経由の多言語ローカライズ
- workflow-state.json 自動更新
- schedule_config.json の min_hours_between_shorts による投稿間隔ガード
"""

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader
from youtube_automation.utils.config import channel_dir as _channel_dir
from youtube_automation.utils.config import load_config
from youtube_automation.utils.exceptions import ConfigError, UploadError, YouTubeAPIError
from youtube_automation.utils.metadata_generator import BAHMetadataGenerator

logger = logging.getLogger(__name__)


class ShortUploader:
    """Shorts アップロード専用エージェント.

    BAHMetadataGenerator にメタデータ生成を委譲し、
    YouTubeAutoUploader にアップロード本体を委譲する責務薄いオーケストレーター。
    """

    def __init__(self):
        self.config = load_config()
        self.channel_dir = _channel_dir()
        self.schedule_config = self._load_schedule_config()
        self.uploader = YouTubeAutoUploader(str(self.channel_dir / "collections"))

    # ─── 設定読み込み ─────────────────────────────────

    def _load_schedule_config(self) -> dict:
        """schedule_config.json を読み込む（存在しない場合は空 dict）."""
        path = self.channel_dir / "config" / "schedule_config.json"
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ─── ファイル読み込み ─────────────────────────────

    def _load_upload_tracking(self, collection_path: Path) -> dict | None:
        """upload_tracking.json を読み込む（存在しなければ None）."""
        tracking_file = collection_path / "20-documentation" / "upload_tracking.json"
        if not tracking_file.exists():
            return None
        with open(tracking_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _find_short_video(self, collection_path: Path, short_num: int | None = None) -> Path | None:
        """Shorts 動画ファイルを検索する.

        - short_num 指定時: `01-master/shorts/short-{NN}-*.mp4`（ラベル付き）
        - 通常: `01-master/short.mp4`
        """
        if short_num is not None:
            prefix = f"short-{short_num:02d}"
            shorts_dir = collection_path / "01-master" / "shorts"
            candidates = sorted(shorts_dir.glob(f"{prefix}*.mp4"))
            if candidates:
                return candidates[0]
            logger.error(f"❌ Shorts 動画が見つかりません: {shorts_dir}/{prefix}*.mp4")
            return None

        candidate = collection_path / "01-master" / "short.mp4"
        if candidate.exists():
            return candidate

        logger.error(f"❌ Shorts 動画が見つかりません: {candidate}")
        return None

    # ─── 公開日計算 ───────────────────────────────────

    def _calculate_short_publish_at(self, collection_path: Path) -> str | None:
        """CC 公開日の翌日 `short_publish_time` で publishAt を算出する.

        1. upload_tracking.json → complete_collection.publish_at（無ければ upload_time）
        2. 翌日 + `config.workflow.post_upload.short_publish_time`
        3. 過去の日時なら None を返す（即時公開 = public）
        """
        tracking = self._load_upload_tracking(collection_path)
        if not tracking:
            logger.error("❌ upload_tracking.json が見つかりません")
            return None

        cc = tracking.get("complete_collection", {})
        tz_name = self.schedule_config.get("schedule", {}).get("timezone", "Asia/Tokyo")
        tz = ZoneInfo(tz_name)

        cc_publish_at = cc.get("publish_at")
        if cc_publish_at:
            cc_dt = datetime.fromisoformat(cc_publish_at)
        elif cc.get("upload_time"):
            cc_dt = datetime.fromisoformat(cc.get("upload_time"))
            if cc_dt.tzinfo is None:
                cc_dt = cc_dt.replace(tzinfo=tz)
        else:
            logger.error("❌ CC の公開日時が取得できません")
            return None

        short_time_str = self.config.workflow.post_upload.short_publish_time
        hour, minute = map(int, short_time_str.split(":"))
        next_day = (cc_dt + timedelta(days=1)).date()
        short_dt = datetime(next_day.year, next_day.month, next_day.day, hour, minute, 0, tzinfo=tz)

        if short_dt <= datetime.now(tz):
            logger.info("📅 公開予定日時が過去のため即時公開 (public)")
            return None

        logger.info(f"📅 Shorts 公開予定: {short_dt.isoformat()}")
        return short_dt.isoformat()

    # ─── メタデータ生成 ───────────────────────────────

    def _generate_metadata(self, collection_path: Path, cc_video_url: str) -> dict:
        """BAHMetadataGenerator 経由で Shorts 用メタデータを生成する."""
        generator = BAHMetadataGenerator(str(collection_path))
        return generator.generate_shorts_metadata(cc_video_url)

    # ─── workflow-state 更新 ──────────────────────────

    def _update_workflow_state(self, collection_path: Path, video_id: str, publish_at: str | None):
        """workflow-state.json の `post_upload.short` を更新する."""
        ws_file = collection_path / "workflow-state.json"
        if not ws_file.exists():
            logger.warning("⚠️  workflow-state.json が見つかりません — 更新をスキップ")
            return

        with open(ws_file, "r", encoding="utf-8") as f:
            ws = json.load(f)

        post_upload = ws.setdefault("post_upload", {})
        post_upload["short"] = {
            "generated": True,
            "uploaded": True,
            "video_id": video_id,
            "video_url": f"https://www.youtube.com/shorts/{video_id}",
            "upload_time": datetime.now().isoformat(),
            "publish_at": publish_at,
        }

        with open(ws_file, "w", encoding="utf-8") as f:
            json.dump(ws, f, indent=2, ensure_ascii=False)

        logger.info("📋 workflow-state.json 更新完了")

    # ─── 投稿間隔チェック ─────────────────────────────

    def _check_upload_interval(self) -> tuple[bool, str]:
        """前回の Shorts アップロードから十分な時間が経過しているかチェックする.

        `schedule_config.json::shorts.min_hours_between_shorts` を参照し、
        `live/` 配下の全コレクションの workflow-state.json から最新の
        Shorts アップロード時刻を取得して比較する。
        """
        min_hours = self.schedule_config.get("shorts", {}).get("min_hours_between_shorts", 24)
        tz_name = self.schedule_config.get("schedule", {}).get("timezone", "Asia/Tokyo")
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)

        live_dir = self.channel_dir / "collections" / "live"
        latest_upload_time = None

        if live_dir.exists():
            for ws_file in live_dir.glob("*/workflow-state.json"):
                try:
                    with open(ws_file, "r", encoding="utf-8") as f:
                        ws = json.load(f)
                    upload_time_str = ws.get("post_upload", {}).get("short", {}).get("upload_time")
                    if upload_time_str:
                        upload_time = datetime.fromisoformat(upload_time_str)
                        if upload_time.tzinfo is None:
                            upload_time = upload_time.replace(tzinfo=tz)
                        if latest_upload_time is None or upload_time > latest_upload_time:
                            latest_upload_time = upload_time
                except (json.JSONDecodeError, ValueError):
                    continue

        if latest_upload_time is None:
            return True, "前回の Shorts アップロード記録なし — 投稿可"

        elapsed_hours = (now - latest_upload_time).total_seconds() / 3600
        if elapsed_hours >= min_hours:
            return True, f"前回から {elapsed_hours:.1f}h 経過（最低 {min_hours}h）— 投稿可"
        remaining = min_hours - elapsed_hours
        return False, f"前回から {elapsed_hours:.1f}h（最低 {min_hours}h 必要）— あと {remaining:.1f}h 待機"

    # ─── オーケストレーション ─────────────────────────

    def upload_short(self, collection_path: Path, short_num: int | None = None) -> dict:
        """Shorts アップロードのメインオーケストレーター.

        1. 投稿間隔チェック
        2. Shorts 動画ファイル検索
        3. CC publish_at から publishAt 計算
        4. メタデータ生成（BAHMetadataGenerator 経由）
        5. アップロード（YouTubeAutoUploader 経由）
        6. workflow-state.json 更新
        """
        collection_path = Path(collection_path).resolve()

        ok, message = self._check_upload_interval()
        if not ok:
            logger.warning(f"⏳ {message}")
            return {"action": "short_upload_blocked", "details": {"reason": message}}

        video_path = self._find_short_video(collection_path, short_num)
        if not video_path:
            return {"action": "short_upload_failed", "details": {"error": "Shorts 動画が見つかりません"}}

        tracking = self._load_upload_tracking(collection_path)
        if not tracking:
            return {"action": "short_upload_failed", "details": {"error": "upload_tracking.json が見つかりません"}}

        cc = tracking.get("complete_collection", {})
        cc_video_url = cc.get("video_url", "")
        if not cc_video_url:
            logger.warning("⚠️  CC の video_url が空です — リンクなしで続行")

        publish_at = self._calculate_short_publish_at(collection_path)
        metadata = self._generate_metadata(collection_path, cc_video_url)
        if publish_at:
            metadata["publish_at"] = publish_at

        thumbnail_path = None
        for tn in ["short-thumbnail.jpg", "short-thumbnail.png"]:
            candidate = collection_path / "10-assets" / tn
            if candidate.exists():
                thumbnail_path = str(candidate)
                break

        logger.info(f"📤 Shorts アップロード開始: {video_path.name}")
        logger.info(f"🎵 コレクション: {collection_path.name}")
        if publish_at:
            logger.info(f"📅 スケジュール公開: {publish_at}")
        else:
            logger.info("📅 即時公開 (public)")

        try:
            video_id = self.uploader.upload_video(str(video_path), metadata, thumbnail_path)
        except (ConfigError, YouTubeAPIError, UploadError) as e:
            logger.error(f"❌ Shorts アップロード失敗: {e}")
            return {"action": "short_upload_failed", "details": {"error": str(e)}}

        if not video_id:
            logger.error("❌ Shorts アップロード失敗")
            return {"action": "short_upload_failed", "details": {"error": "アップロード失敗"}}

        video_url = f"https://www.youtube.com/shorts/{video_id}"
        self._update_workflow_state(collection_path, video_id, publish_at)

        logger.info(f"✅ Shorts アップロード完了: {video_url}")
        return {
            "action": "short_uploaded",
            "details": {
                "video_id": video_id,
                "video_url": video_url,
                "publish_at": publish_at,
                "title": metadata["title"],
            },
        }

    def show_plan(self, collection_path: Path, short_num: int | None = None):
        """ドライラン — 計算結果のみ表示する."""
        collection_path = Path(collection_path).resolve()

        print(f"📋 Shorts アップロード計画: {collection_path.name}")
        print()

        ok, message = self._check_upload_interval()
        status = "✅" if ok else "⏳"
        print(f"  {status} 投稿間隔: {message}")
        print()

        video_path = self._find_short_video(collection_path, short_num)
        if video_path:
            print(f"  📹 動画: {video_path.name}")
        else:
            print("  ❌ Shorts 動画が見つかりません")
            return

        tracking = self._load_upload_tracking(collection_path)
        if not tracking:
            print("  ❌ upload_tracking.json が見つかりません")
            return

        cc = tracking.get("complete_collection", {})
        print(f"  🔗 CC URL: {cc.get('video_url', '(なし)')}")
        print(f"  📅 CC publish_at: {cc.get('publish_at', '(即時公開)')}")

        publish_at = self._calculate_short_publish_at(collection_path)
        print()
        if publish_at:
            print(f"  📅 Shorts 公開予定: {publish_at}")
        else:
            print("  📅 Shorts 公開: 即時公開 (public)")

        cc_video_url = cc.get("video_url", "")
        metadata = self._generate_metadata(collection_path, cc_video_url)
        print()
        print(f"  📝 タイトル: {metadata['title']}")
        print(f"  🏷️  タグ: {', '.join(metadata['tags'][:5])}...")
        loc_count = len(metadata.get("localizations", {}))
        print(f"  🌐 ローカライズ: {loc_count} 言語")
        print()
        print("  ── 説明文プレビュー ──")
        for line in metadata["description"].split("\n"):
            print(f"  {line}")


def main():
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Short Uploader — Shorts 動画アップロード")
    parser.add_argument("collection_path", help="コレクションパス")
    parser.add_argument("--dry-run", action="store_true", help="ドライラン（アップロードせず計算のみ）")
    parser.add_argument("--short-num", type=int, default=None, help="Shorts 番号（複数 Shorts 時）")

    args = parser.parse_args()

    try:
        uploader = ShortUploader()
        collection_path = Path(args.collection_path)

        if args.dry_run:
            uploader.show_plan(collection_path, args.short_num)
        else:
            result = uploader.upload_short(collection_path, args.short_num)
            if result["action"] == "short_upload_failed":
                print(f"❌ {result['details']['error']}")
                sys.exit(1)

    except KeyboardInterrupt:
        print("\n🛑 処理が中断されました")
    except (ConfigError, YouTubeAPIError, UploadError) as e:
        print(f"❌ エラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
