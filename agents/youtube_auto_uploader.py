#!/usr/bin/env python3
"""
8-Bit Adventure Hub (8BAH) - YouTube 自動アップローダー
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
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# プロジェクトルートをパスに追加
sys.path.append(str(Path(__file__).parent.parent))

from auth.oauth_handler import YouTubeOAuthHandler
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from utils.channel_config import ChannelConfig
from utils.metadata_generator import BAHMetadataGenerator


class YouTubeAutoUploader:
    """YouTube自動アップロードメインクラス"""

    def __init__(self, collections_root: str = None):
        """
        初期化

        Args:
            collections_root (str): collections/ ディレクトリのパス
        """
        if collections_root is None:
            from utils.channel_config import ChannelConfig
            collections_root = ChannelConfig.channel_dir() / 'collections'

        self.collections_root = Path(collections_root)
        self.auth_handler = YouTubeOAuthHandler()
        self.youtube_service = None
        self.upload_results = []

    def initialize(self):
        """YouTube API 初期化"""
        logger.info("🔐 YouTube API 認証中...")
        self.youtube_service = self.auth_handler.get_youtube_service()
        logger.info("✅ YouTube API 準備完了")

    def upload_video(self, video_path: str, metadata: Dict, thumbnail_path: str = None) -> Optional[str]:
        """
        動画をYouTubeにアップロード

        Args:
            video_path (str): 動画ファイルパス
            metadata (Dict): メタデータ
            thumbnail_path (str): サムネイルファイルパス

        Returns:
            str: アップロードされた動画のID（失敗時はNone）
        """
        if not self.youtube_service:
            self.initialize()

        video_file = Path(video_path)
        if not video_file.exists():
            logger.error(f"❌ 動画ファイルが見つかりません: {video_path}")
            return None

        logger.info(f"📤 アップロード開始: {video_file.name}")

        # メディアファイル準備
        media = MediaFileUpload(
            str(video_file),
            chunksize=-1,  # 一括アップロード
            resumable=True
        )

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
            logger.info(f"📅 スケジュール公開: {metadata['publish_at']}")

        body = {
            'snippet': {
                'title': metadata['title'][:100],  # YouTube上限100文字
                'description': metadata['description'][:5000],  # YouTube上限5000文字
                'tags': metadata['tags'][:50],  # YouTube上限50タグ
                'categoryId': metadata.get('category_id', '10'),
                'defaultLanguage': metadata.get('language', 'en'),
                'defaultAudioLanguage': metadata.get('language', 'en'),
            },
            'status': status_body
        }

        if metadata.get('localizations'):
            body['localizations'] = metadata['localizations']

        try:
            # 動画アップロード実行
            insert_request = self.youtube_service.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )

            # プログレス表示しながらアップロード
            video_id = self._resumable_upload(insert_request, video_file.name)

            if video_id:
                logger.info(f"✅ アップロード成功: {video_id}")

                # サムネイル設定
                if thumbnail_path and Path(thumbnail_path).exists():
                    self._set_thumbnail(video_id, thumbnail_path)

                return video_id
            else:
                logger.error(f"❌ アップロード失敗: {video_file.name}")
                return None

        except HttpError as e:
            logger.error(f"❌ YouTube API エラー: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ 予期しないエラー: {e}")
            return None

    def _resumable_upload(self, insert_request, filename: str) -> Optional[str]:
        """
        再開可能アップロード実行

        Args:
            insert_request: YouTube API リクエスト
            filename: ファイル名（表示用）

        Returns:
            str: 動画ID（失敗時はNone）
        """
        response = None
        error = None
        retry = 0

        while response is None:
            try:
                logger.info(f"📤 アップロード中: {filename} (試行{retry + 1})")
                status, response = insert_request.next_chunk()

                if status:
                    progress = int(status.progress() * 100)
                    logger.info(f"   進捗: {progress}%")

            except HttpError as e:
                if e.resp.status in [500, 502, 503, 504]:
                    # 再試行可能エラー
                    error = f"再試行可能エラー: {e}"
                    time.sleep(2 ** retry)
                    retry += 1
                    if retry > 5:
                        logger.error(f"❌ リトライ上限到達: {error}")
                        return None
                else:
                    # 致命的エラー
                    logger.error(f"❌ 致命的エラー: {e}")
                    return None

            except Exception as e:
                logger.error(f"❌ アップロードエラー: {e}")
                return None

        if 'id' in response:
            return response['id']
        else:
            logger.error(f"❌ レスポンスに動画IDがありません: {response}")
            return None

    def _compress_thumbnail(self, thumbnail_path: Path, max_bytes: int = 2_097_152) -> Path:
        """サムネイルが max_bytes を超える場合、ffmpeg で JPEG 圧縮した一時ファイルを返す"""
        if thumbnail_path.stat().st_size <= max_bytes:
            return thumbnail_path

        import tempfile
        import subprocess
        compressed = Path(tempfile.mktemp(suffix='.jpg'))
        for quality in [2, 5]:  # ffmpeg -qscale:v 2=高品質, 5=中品質
            subprocess.run(
                ['ffmpeg', '-y', '-i', str(thumbnail_path), '-qscale:v', str(quality), str(compressed)],
                capture_output=True,
            )
            if compressed.exists() and compressed.stat().st_size <= max_bytes:
                logger.info(f"🗜️  サムネイル圧縮(q{quality}): {thumbnail_path.stat().st_size / 1024:.0f}KB → {compressed.stat().st_size / 1024:.0f}KB")
                return compressed

        logger.warning(f"⚠️  サムネイル圧縮後も {compressed.stat().st_size / 1024:.0f}KB — 上限超過")
        return thumbnail_path

    def _set_thumbnail(self, video_id: str, thumbnail_path: str):
        """
        サムネイル設定（2MB 超は自動圧縮）

        Args:
            video_id (str): 動画ID
            thumbnail_path (str): サムネイルファイルパス
        """
        try:
            thumbnail_file = self._compress_thumbnail(Path(thumbnail_path))

            self.youtube_service.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_file))
            ).execute()

            logger.info(f"✅ サムネイル設定完了: {Path(thumbnail_path).name}")

            # 一時ファイルのクリーンアップ
            if thumbnail_file != Path(thumbnail_path) and thumbnail_file.exists():
                thumbnail_file.unlink()

        except Exception as e:
            logger.warning(f"⚠️  サムネイル設定エラー: {e}")

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

        if publish_at:
            metadata['publish_at'] = publish_at

        # サムネイル検索（thumbnail.png を優先）
        thumbnail_path = None
        thumbnail_exact = collection_dir / '10-assets' / 'thumbnail.png'
        if thumbnail_exact.exists():
            thumbnail_path = str(thumbnail_exact)
        else:
            thumbnail_files = list(collection_dir.glob('10-assets/*.png'))
            thumbnail_path = str(thumbnail_files[0]) if thumbnail_files else None

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
