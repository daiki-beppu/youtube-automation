#!/usr/bin/env python3
"""
YouTube 自動アップローダー
collections/ の動画を自動的にYouTubeにアップロード

Features:
- Complete Collection 自動アップロード
- メタデータ自動生成・最適化
- サムネイル自動設定
- アップロード結果レポート
- エラーハンドリング・リトライ機能
"""

import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

import utils._path_setup  # noqa: F401, E402
from utils.channel_config import ChannelConfig  # noqa: E402
from utils.metadata_generator import BAHMetadataGenerator  # noqa: E402
from utils.upload_core import YouTubeUploadCore  # noqa: E402


class YouTubeAutoUploader(YouTubeUploadCore):
    """YouTube自動アップロードメインクラス

    YouTubeUploadCore を継承し、コレクション単位のアップロード機能を提供する。
    コアのアップロード・サムネイル・リトライロジックは YouTubeUploadCore に委譲。
    """

    def __init__(self, collections_root: str = None):
        """
        初期化

        Args:
            collections_root (str): collections/ ディレクトリのパス
        """
        super().__init__()

        if collections_root is None:
            collections_root = ChannelConfig.channel_dir() / 'collections'

        self.collections_root = Path(collections_root)
        self.upload_results = []

    @property
    def youtube_service(self):
        """後方互換: youtube_service は youtube の別名"""
        return self.youtube

    @youtube_service.setter
    def youtube_service(self, value):
        self.youtube = value

    def upload_video(self, video_path: str, metadata: Dict, thumbnail_path: str = None) -> Optional[str]:
        """
        メタデータ辞書から YouTube API ボディを構築してアップロード

        Args:
            video_path (str): 動画ファイルパス
            metadata (Dict): メタデータ（title, description, tags, privacy_status 等）
            thumbnail_path (str): サムネイルファイルパス

        Returns:
            str: アップロードされた動画のID（失敗時はNone）
        """
        # リクエストボディ作成
        status_body = {
            'privacyStatus': metadata.get('privacy_status', 'private'),
            'selfDeclaredMadeForKids': False,
            'containsSyntheticMedia': False,
        }

        # スケジュール公開: publishAt 指定時は private 必須
        if metadata.get('publish_at'):
            status_body['privacyStatus'] = 'private'
            status_body['publishAt'] = metadata['publish_at']
            logger.info(f"スケジュール公開: {metadata['publish_at']}")

        body = {
            'snippet': {
                'title': metadata['title'][:100],  # YouTube上限100文字
                'description': metadata['description'][:5000],  # YouTube上限5000文字
                'tags': metadata['tags'][:50],  # YouTube上限50タグ
                'categoryId': metadata.get('category_id', '10'),
                'defaultLanguage': metadata.get('language', 'en'),
                'defaultAudioLanguage': metadata.get('language', 'en'),
            },
            'status': status_body,
        }

        if metadata.get('localizations'):
            body['localizations'] = metadata['localizations']

        return super().upload_video(video_path, body, thumbnail_path)

    def _load_descriptions_md(self, collection_dir: Path) -> dict | None:
        """descriptions.md から事前生成メタデータを読み込み

        /description スキルが生成した descriptions.md が存在する場合、
        title / description / tags を抽出して返す。
        ファイルが存在しない or パース失敗時は None（BAHMetadataGenerator にフォールバック）。
        """
        desc_path = collection_dir / '20-documentation' / 'descriptions.md'
        if not desc_path.exists():
            return None

        text = desc_path.read_text(encoding='utf-8')

        title = self._extract_md_section(text, 'タイトル案')
        description = self._extract_md_section(text, 'Complete Collection 概要欄')
        tags_raw = self._extract_md_section(text, 'タグ（YouTube タグ欄）')

        if not (title and description):
            logger.warning("⚠️  descriptions.md のパースに失敗 — BAHMetadataGenerator にフォールバック")
            return None

        tags = [t.strip() for t in tags_raw.replace('\n', ',').split(',') if t.strip()] if tags_raw else []

        logger.info("📄 descriptions.md からメタデータを読み込み")
        return {'title': title.strip(), 'description': description.strip(), 'tags': tags}

    @staticmethod
    def _extract_body_for_localizations(description: str) -> str | None:
        """キュレーション済み概要欄から本文部分（フッター前）を抽出

        ローカライゼーション用: シーンフック + タイムスタンプ + ブリッジテキストを返す。
        フッター（Perfect for / Usage & Attribution 等）は generate_localizations() が各言語で付加する。
        """
        for marker in ['Perfect for:', '🎮 Perfect for', '─────', '📝 Usage', 'Usage & Attribution']:
            idx = description.find(marker)
            if idx > 0:
                return description[:idx].rstrip()
        return None

    @staticmethod
    def _extract_md_section(text: str, heading: str) -> str | None:
        """Markdown の ## heading 直後のコードフェンス内容を抽出"""
        pattern = rf'## {re.escape(heading)}\s*\n+```\n(.*?)```'
        m = re.search(pattern, text, re.DOTALL)
        return m.group(1).strip() if m else None

    def upload_collection(self, collection_path: str, publish_at: str = None) -> Dict:
        """
        Complete Collection のアップロード

        Args:
            collection_path (str): コレクションディレクトリパス
            publish_at (str): スケジュール公開日時（ISO 8601）

        Returns:
            Dict: アップロード結果
        """
        collection_dir = Path(collection_path)
        if not collection_dir.exists():
            raise FileNotFoundError(f"コレクションディレクトリが見つかりません: {collection_path}")

        logger.info(f"🎵 コレクションアップロード開始: {collection_dir.name}")
        logger.info(f"📁 パス: {collection_dir}")

        # メタデータ生成器初期化
        metadata_gen = BAHMetadataGenerator(str(collection_dir))

        results = {
            'collection_name': metadata_gen.collection_name,
            'collection_path': str(collection_dir),
            'start_time': datetime.now(),
            'complete_video': None,
            'errors': []
        }

        # Complete Collection アップロード
        complete_result = self._upload_complete_collection(collection_dir, metadata_gen, publish_at=publish_at)
        results['complete_video'] = complete_result

        results['end_time'] = datetime.now()
        results['duration'] = results['end_time'] - results['start_time']

        # 結果レポート
        self._print_upload_report(results)

        return results

    def _upload_complete_collection(
        self, collection_dir: Path, metadata_gen: BAHMetadataGenerator, publish_at: str = None
    ) -> Optional[Dict]:
        """Complete Collection 動画アップロード"""
        logger.info("📹 Complete Collection アップロード準備中...")

        # マスター動画ファイル検索
        video_files = list(collection_dir.glob('03-Individual-movie/*master*.mp4'))
        if not video_files:
            video_files = list(collection_dir.glob('01-master/*.mp4'))

        if not video_files:
            error_msg = "マスター動画ファイルが見つかりません"
            logger.error(f"❌ {error_msg}")
            return {'error': error_msg}

        master_video = video_files[0]

        # メタデータ生成（BAHMetadataGenerator — localizations 等）
        metadata = metadata_gen.generate_complete_collection_metadata()

        # descriptions.md が存在すれば title/description/tags を上書き
        prebuilt = self._load_descriptions_md(collection_dir)
        if prebuilt:
            metadata['title'] = prebuilt['title']
            metadata['description'] = prebuilt['description']
            if prebuilt['tags']:
                metadata['tags'] = prebuilt['tags']

            # ローカライゼーションにもキュレーション済みの本文を使用
            curated_body = self._extract_body_for_localizations(prebuilt['description'])
            if curated_body and hasattr(metadata_gen, '_last_title_vars'):
                metadata['localizations'] = metadata_gen.generate_localizations(
                    metadata_gen._last_title_vars, curated_body
                )

        if publish_at:
            metadata['publish_at'] = publish_at

        # サムネイル検索（thumbnail.jpg を優先）
        thumbnail_path = None
        for tn in ['thumbnail.jpg', 'thumbnail.png', 'main.jpg', 'main.png']:
            candidate = collection_dir / '10-assets' / tn
            if candidate.exists():
                thumbnail_path = str(candidate)
                break

        # アップロード実行
        video_id = self.upload_video(str(master_video), metadata, thumbnail_path)

        if video_id:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            return {
                'video_id': video_id,
                'video_url': video_url,
                'title': metadata['title'],
                'file_path': str(master_video),
                'thumbnail_path': thumbnail_path
            }
        else:
            return {'error': 'Complete Collection アップロード失敗'}

    def _print_upload_report(self, results: Dict):
        """アップロード結果レポート表示"""
        logger.info("📊 YouTube アップロード結果レポート")
        logger.info(f"🎵 コレクション: {results['collection_name']}")
        logger.info(f"📁 パス: {results['collection_path']}")
        logger.info(f"⏱️  実行時間: {results['duration']}")
        logger.info(f"📅 実行日時: {results['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")

        # Complete Collection 結果
        if results['complete_video']:
            if 'video_id' in results['complete_video']:
                logger.info(f"✅ Complete Collection: {results['complete_video']['video_url']}")
            else:
                logger.error(f"❌ Complete Collection: {results['complete_video']['error']}")

    def process_collections_directory(self, status_filter: List[str] = None) -> Dict:
        """
        collections/ ディレクトリ内の対象コレクションを一括処理

        Args:
            status_filter (List[str]): 処理対象ステータス（例: ['ready']）

        Returns:
            Dict: 全体の処理結果
        """
        if status_filter is None:
            status_filter = ['ready']  # デフォルトはready状態のみ

        config = ChannelConfig.load()
        logger.info(f"🎵 {config.channel_name} - 一括YouTube アップロード")
        logger.info(f"📁 collections ディレクトリ: {self.collections_root}")
        logger.info(f"🎯 対象ステータス: {status_filter}")

        # 対象コレクション検索
        target_collections = []

        for status in status_filter:
            status_dir = self.collections_root / status
            if status_dir.exists():
                collections = [d for d in status_dir.iterdir()
                             if d.is_dir() and not d.name.startswith('.')]
                target_collections.extend([(status, col) for col in collections])

        if not target_collections:
            logger.error("❌ 処理対象のコレクションが見つかりません")
            return {'error': '処理対象コレクションなし'}

        logger.info(f"📋 処理対象: {len(target_collections)}コレクション")

        all_results = {
            'start_time': datetime.now(),
            'target_collections': len(target_collections),
            'results': [],
            'summary': {'success': 0, 'error': 0}
        }

        # 各コレクションを処理
        for i, (status, collection_dir) in enumerate(target_collections, 1):
            logger.info(f"🎵 [{i}/{len(target_collections)}] {collection_dir.name}")

            try:
                result = self.upload_collection(str(collection_dir))
                all_results['results'].append(result)

                # 成功判定
                has_success = bool(result.get('complete_video', {}).get('video_id'))

                if has_success:
                    all_results['summary']['success'] += 1
                    # ready -> live への移動（オプション）
                    # self._move_collection_to_live(collection_dir)
                else:
                    all_results['summary']['error'] += 1

            except Exception as e:
                error_msg = f"コレクション処理エラー {collection_dir.name}: {e}"
                logger.error(f"❌ {error_msg}")
                all_results['results'].append({
                    'collection_name': collection_dir.name,
                    'error': error_msg
                })
                all_results['summary']['error'] += 1

        all_results['end_time'] = datetime.now()
        all_results['duration'] = all_results['end_time'] - all_results['start_time']

        # 全体結果レポート
        self._print_batch_report(all_results)

        return all_results

    def _print_batch_report(self, all_results: Dict):
        """一括処理結果レポート"""
        logger.info("🎉 YouTube 一括アップロード完了レポート")
        logger.info(f"📊 処理結果: {all_results['summary']['success']} 成功 / {all_results['summary']['error']} エラー")
        logger.info(f"⏱️  総実行時間: {all_results['duration']}")
        logger.info(f"📅 実行日時: {all_results['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")

def main():
    """メイン関数"""
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    config = ChannelConfig.load()
    parser = argparse.ArgumentParser(description=f'{config.channel_short} YouTube 自動アップローダー')
    parser.add_argument('--collection', '-c', help='特定コレクションのパス')
    parser.add_argument('--batch', '-b', action='store_true',
                       help='collections/ready/ の一括処理')
    parser.add_argument('--status', '-s', nargs='+', default=['ready'],
                       help='一括処理対象ステータス')

    args = parser.parse_args()

    try:
        uploader = YouTubeAutoUploader()
        uploader.initialize()

        if args.collection:
            # 単一コレクション処理
            uploader.upload_collection(args.collection)
        elif args.batch:
            # 一括処理
            uploader.process_collections_directory(args.status)
        else:
            print("使用法:")
            print("  単一コレクション: python youtube_auto_uploader.py -c path/to/collection")
            print("  一括処理: python youtube_auto_uploader.py --batch")

    except KeyboardInterrupt:
        print("\n🛑 ユーザーによって中断されました")
    except Exception as e:
        print(f"❌ エラー: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
