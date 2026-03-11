#!/usr/bin/env python3
"""
Short Uploader — ショート動画アップロード専用

CC（Complete Collection）の実際の公開日から short_delay_days を加算して
正確な公開日を算出し、Shorts 動画をアップロードする。

Features:
- CC publish_at 基準の公開日計算（upload_tracking.json から取得）
- 15言語ローカライズ対応
- workflow-state.json 自動更新
"""

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# プロジェクトルートをパスに追加
sys.path.append(str(Path(__file__).parent.parent))

from agents.youtube_auto_uploader import YouTubeAutoUploader  # noqa: E402
from utils.channel_config import ChannelConfig  # noqa: E402


class ShortUploader:
    """Short Uploader — ショート動画アップロード専用

    CC の実際の公開日（upload_tracking.json）から short_delay_days を
    加算して正確な公開日を算出する。
    """

    def __init__(self):
        config = ChannelConfig.load()
        channel_dir = ChannelConfig.channel_dir()
        self.config = config
        self.channel_dir = channel_dir
        self.schedule_config = self._load_schedule_config()
        self.uploader = YouTubeAutoUploader(str(channel_dir / 'collections'))

    def _load_schedule_config(self) -> dict:
        """schedule_config.json 読み込み"""
        path = self.channel_dir / 'config' / 'schedule_config.json'
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    # ─── ファイル読み込み ─────────────────────────────

    def _load_upload_tracking(self, collection_path: Path) -> dict | None:
        """upload_tracking.json 読み込み"""
        tracking_file = collection_path / '20-documentation' / 'upload_tracking.json'
        if not tracking_file.exists():
            return None
        with open(tracking_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _load_workflow_state(self, collection_path: Path) -> dict | None:
        """workflow-state.json 読み込み"""
        ws_file = collection_path / 'workflow-state.json'
        if not ws_file.exists():
            return None
        with open(ws_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _find_short_video(self, collection_path: Path, short_num: int | None = None) -> Path | None:
        """ショート動画ファイルを検索

        1. short_num 指定時: 01-master/shorts/short-{NN}.mp4
        2. 通常: 01-master/short.mp4
        """
        if short_num is not None:
            candidate = collection_path / '01-master' / 'shorts' / f'short-{short_num:02d}.mp4'
            if candidate.exists():
                return candidate
            logger.error(f"❌ ショート動画が見つかりません: {candidate}")
            return None

        candidate = collection_path / '01-master' / 'short.mp4'
        if candidate.exists():
            return candidate

        logger.error(f"❌ ショート動画が見つかりません: {candidate}")
        return None

    # ─── 公開日計算 ───────────────────────────────────

    def _calculate_short_publish_at(self, collection_path: Path) -> str | None:
        """CC publish_at + short_delay_days で公開日を算出

        1. upload_tracking.json → complete_collection.publish_at を取得
        2. publish_at があればパース、なければ upload_time + timezone でフォールバック
        3. + short_delay_hours（channel_config.json、デフォルト 12時間）
        4. 過去の日時なら None を返す（即時公開 = public）
        """
        tracking = self._load_upload_tracking(collection_path)
        if not tracking:
            logger.error("❌ upload_tracking.json が見つかりません")
            return None

        cc = tracking.get('complete_collection', {})
        tz_name = self.schedule_config.get('schedule', {}).get('timezone', 'Asia/Tokyo')
        tz = ZoneInfo(tz_name)

        # CC の公開日時を取得
        cc_publish_at = cc.get('publish_at')
        if cc_publish_at:
            cc_dt = datetime.fromisoformat(cc_publish_at)
        elif cc.get('upload_time'):
            # publish_at がない = 即時公開だった → upload_time を基準に
            cc_dt = datetime.fromisoformat(cc.get('upload_time'))
            if cc_dt.tzinfo is None:
                cc_dt = cc_dt.replace(tzinfo=tz)
        else:
            logger.error("❌ CC の公開日時が取得できません")
            return None

        # CC 公開日時 + short_delay_hours を加算
        delay_hours = self.config._data.get('post_upload', {}).get('short_delay_hours', 12)
        short_dt = cc_dt + timedelta(hours=delay_hours)

        # 過去なら即時公開
        now = datetime.now(tz)
        if short_dt <= now:
            logger.info("📅 公開予定日時が過去のため即時公開 (public)")
            return None

        logger.info(f"📅 ショート公開予定: {short_dt.isoformat()}")
        return short_dt.isoformat()

    # ─── メタデータ生成 ───────────────────────────────

    def _generate_metadata(self, collection_path: Path, cc_video_url: str) -> dict:
        """Shorts 用メタデータ生成（EN デフォルト）"""
        ws = self._load_workflow_state(collection_path)
        collection_name = ws.get('collection_name', collection_path.name) if ws else collection_path.name
        theme = ws.get('theme', '') if ws else ''

        channel_name = self.config.channel_name
        tagline = self.config.tagline
        hashtags = self.config.hashtag_line

        # タイトル
        title = f"{collection_name} ✦ {channel_name} #Shorts"

        # 説明文
        description = '\n'.join([
            f"{collection_name} | {channel_name}",
            "",
            f"♫ Full 2-hour collection → {cc_video_url}",
            "",
            tagline,
            "",
            f"{hashtags} #Shorts",
        ])

        # タグ
        base_tags = self.config.base_tags
        theme_tags = self.config.theme_tags.get(theme, [])
        tags = ['Shorts'] + base_tags + theme_tags

        # ローカライズ
        localizations = self._generate_localizations(collection_name, cc_video_url)

        return {
            'title': title[:100],
            'description': description[:5000],
            'tags': tags[:50],
            'category_id': self.config.category_id,
            'privacy_status': 'public',
            'language': self.config.language,
            'localizations': localizations,
        }

    def _generate_localizations(self, collection_name: str, cc_video_url: str) -> dict:
        """15言語の title/description 生成"""
        localizations = {}
        loc_config = self.config.localizations_config
        channel_name = self.config.channel_name
        tagline_default = self.config.tagline

        for lang in loc_config.get('supported_languages', []):
            lang_data = loc_config.get('languages', {}).get(lang, {})

            # short_title_template が定義されていなければスキップ
            short_title_tpl = lang_data.get('short_title_template')
            if not short_title_tpl:
                continue

            # タイトル
            loc_title = short_title_tpl.format(
                theme=collection_name,
                channel_name=channel_name,
            )[:100]

            # 説明文
            short_desc_tpl = lang_data.get('short_description_template')
            tagline = lang_data.get('description', {}).get('tagline', tagline_default)

            if short_desc_tpl:
                loc_desc = short_desc_tpl.format(
                    collection_name=collection_name,
                    channel_name=channel_name,
                    cc_video_url=cc_video_url,
                    tagline=tagline,
                )[:5000]
            else:
                loc_desc = '\n'.join([
                    f"{collection_name} | {channel_name}",
                    "",
                    f"♫ → {cc_video_url}",
                    "",
                    tagline,
                ])[:5000]

            localizations[lang] = {
                'title': loc_title,
                'description': loc_desc,
            }

        return localizations

    # ─── workflow-state 更新 ──────────────────────────

    def _update_workflow_state(self, collection_path: Path, video_id: str, publish_at: str | None):
        """workflow-state.json の post_upload.short を更新"""
        ws_file = collection_path / 'workflow-state.json'
        if not ws_file.exists():
            logger.warning("⚠️  workflow-state.json が見つかりません — 更新をスキップ")
            return

        with open(ws_file, 'r', encoding='utf-8') as f:
            ws = json.load(f)

        post_upload = ws.setdefault('post_upload', {})
        post_upload['short'] = {
            'generated': True,
            'uploaded': True,
            'video_id': video_id,
            'video_url': f"https://www.youtube.com/shorts/{video_id}",
            'upload_time': datetime.now().isoformat(),
            'publish_at': publish_at,
        }

        with open(ws_file, 'w', encoding='utf-8') as f:
            json.dump(ws, f, indent=2, ensure_ascii=False)

        logger.info("📋 workflow-state.json 更新完了")

    # ─── オーケストレーション ─────────────────────────

    def upload_short(self, collection_path: Path, short_num: int | None = None) -> dict:
        """メインオーケストレーター

        1. ショート動画ファイルを検索
        2. CC の公開日から publish_at を計算
        3. メタデータ生成
        4. アップロード実行
        5. workflow-state.json 更新
        """
        collection_path = Path(collection_path).resolve()

        # ショート動画検索
        video_path = self._find_short_video(collection_path, short_num)
        if not video_path:
            return {"action": "short_upload_failed", "details": {"error": "ショート動画が見つかりません"}}

        # CC 動画 URL 取得
        tracking = self._load_upload_tracking(collection_path)
        if not tracking:
            return {"action": "short_upload_failed", "details": {"error": "upload_tracking.json が見つかりません"}}

        cc = tracking.get('complete_collection', {})
        cc_video_url = cc.get('video_url', '')
        if not cc_video_url:
            logger.warning("⚠️  CC の video_url が空です — リンクなしで続行")

        # 公開日計算
        publish_at = self._calculate_short_publish_at(collection_path)

        # メタデータ生成
        metadata = self._generate_metadata(collection_path, cc_video_url)
        if publish_at:
            metadata['publish_at'] = publish_at

        # サムネイル（ショートは通常サムネイルなし、あれば使う）
        thumbnail_path = None
        for tn in ['short-thumbnail.jpg', 'short-thumbnail.png']:
            candidate = collection_path / '10-assets' / tn
            if candidate.exists():
                thumbnail_path = str(candidate)
                break

        # アップロード実行
        logger.info(f"📤 ショートアップロード開始: {video_path.name}")
        logger.info(f"🎵 コレクション: {collection_path.name}")
        if publish_at:
            logger.info(f"📅 スケジュール公開: {publish_at}")
        else:
            logger.info("📅 即時公開 (public)")

        video_id = self.uploader.upload_video(str(video_path), metadata, thumbnail_path)

        if video_id:
            video_url = f"https://www.youtube.com/shorts/{video_id}"
            self._update_workflow_state(collection_path, video_id, publish_at)

            logger.info(f"✅ ショートアップロード完了: {video_url}")
            return {
                "action": "short_uploaded",
                "details": {
                    "video_id": video_id,
                    "video_url": video_url,
                    "publish_at": publish_at,
                    "title": metadata['title'],
                },
            }
        else:
            logger.error("❌ ショートアップロード失敗")
            return {"action": "short_upload_failed", "details": {"error": "アップロード失敗"}}

    def show_plan(self, collection_path: Path, short_num: int | None = None):
        """ドライラン — 計算結果のみ表示"""
        collection_path = Path(collection_path).resolve()

        print(f"📋 ショートアップロード計画: {collection_path.name}")
        print()

        # 動画ファイル確認
        video_path = self._find_short_video(collection_path, short_num)
        if video_path:
            print(f"  📹 動画: {video_path.name}")
        else:
            print("  ❌ ショート動画が見つかりません")
            return

        # CC 情報
        tracking = self._load_upload_tracking(collection_path)
        if tracking:
            cc = tracking.get('complete_collection', {})
            print(f"  🔗 CC URL: {cc.get('video_url', '(なし)')}")
            print(f"  📅 CC publish_at: {cc.get('publish_at', '(即時公開)')}")
        else:
            print("  ❌ upload_tracking.json が見つかりません")
            return

        # 公開日計算
        publish_at = self._calculate_short_publish_at(collection_path)
        print()
        if publish_at:
            print(f"  📅 ショート公開予定: {publish_at}")
        else:
            print("  📅 ショート公開: 即時公開 (public)")

        # メタデータプレビュー
        cc_video_url = cc.get('video_url', '')
        metadata = self._generate_metadata(collection_path, cc_video_url)
        print()
        print(f"  📝 タイトル: {metadata['title']}")
        print(f"  🏷️  タグ: {', '.join(metadata['tags'][:5])}...")
        loc_count = len(metadata.get('localizations', {}))
        print(f"  🌐 ローカライズ: {loc_count} 言語")
        print()
        print("  ── 説明文プレビュー ──")
        for line in metadata['description'].split('\n'):
            print(f"  {line}")


def main():
    """メイン関数"""
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description='Short Uploader — ショート動画アップロード')
    parser.add_argument('collection_path', help='コレクションパス')
    parser.add_argument('--dry-run', action='store_true', help='ドライラン（アップロードせず計算のみ）')
    parser.add_argument('--short-num', type=int, default=None, help='ショート番号（複数ショート時）')

    args = parser.parse_args()

    try:
        uploader = ShortUploader()
        collection_path = Path(args.collection_path)

        if args.dry_run:
            uploader.show_plan(collection_path, args.short_num)
        else:
            result = uploader.upload_short(collection_path, args.short_num)
            if result['action'] == 'short_upload_failed':
                print(f"❌ {result['details']['error']}")
                sys.exit(1)

    except KeyboardInterrupt:
        print("\n🛑 処理が中断されました")
    except Exception as e:
        print(f"❌ エラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
