"""
YouTube Upload Core - 動画アップロード・サムネイル設定の共通コア機能

YouTubeAutoUploader / VideoUploader 等で重複していたアップロードロジックを
単一モジュールに集約。各アップローダーはこのクラスを継承または委譲で利用する。
"""

import logging
import time
from pathlib import Path
from typing import Optional

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from utils.youtube_service import get_youtube

logger = logging.getLogger(__name__)


class YouTubeUploadCore:
    """YouTube 動画アップロードの共通コア機能。

    提供するメソッド:
        - upload_video(): 動画アップロード（resumable + サムネイル設定）
        - set_thumbnail(): サムネイル設定（2MB 超は自動圧縮）
        - _resumable_upload(): 再開可能アップロード実行（リトライ付き）
        - _compress_thumbnail(): サムネイルを 2MB 以下に圧縮
    """

    def __init__(self):
        self.youtube = None

    def initialize(self):
        """YouTube API サービスを初期化"""
        logger.info("YouTube API 認証中...")
        self.youtube = get_youtube()
        logger.info("YouTube API 準備完了")

    def _ensure_service(self):
        """YouTube サービスが未初期化なら初期化"""
        if not self.youtube:
            self.initialize()

    def upload_video(self, video_path: str, body: dict, thumbnail_path: str = None) -> Optional[str]:
        """動画をアップロードして video_id を返す。

        Args:
            video_path: 動画ファイルパス
            body: YouTube API リクエストボディ（snippet, status 等）
            thumbnail_path: サムネイルファイルパス（省略時はサムネイル設定をスキップ）

        Returns:
            アップロードされた動画の video_id。失敗時は None。
        """
        self._ensure_service()

        video_file = Path(video_path)
        if not video_file.exists():
            logger.error(f"動画ファイルが見つかりません: {video_path}")
            return None

        logger.info(f"アップロード開始: {video_file.name}")

        media = MediaFileUpload(
            str(video_file),
            chunksize=-1,  # 一括アップロード
            resumable=True,
        )

        try:
            insert_request = self.youtube.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media,
            )

            video_id = self._resumable_upload(insert_request, video_file.name)

            if video_id:
                logger.info(f"アップロード成功: {video_id}")

                if thumbnail_path and Path(thumbnail_path).exists():
                    self.set_thumbnail(video_id, thumbnail_path)

                return video_id
            else:
                logger.error(f"アップロード失敗: {video_file.name}")
                return None

        except HttpError as e:
            logger.error(f"YouTube API エラー: {e}")
            return None
        except Exception as e:
            logger.error(f"予期しないエラー: {e}")
            return None

    def _resumable_upload(self, insert_request, filename: str) -> Optional[str]:
        """再開可能アップロード実行（リトライ付き）。

        Args:
            insert_request: YouTube API リクエスト
            filename: ファイル名（ログ表示用）

        Returns:
            動画ID。失敗時は None。
        """
        response = None
        error = None
        retry = 0

        while response is None:
            try:
                logger.info(f"アップロード中: {filename} (試行{retry + 1})")
                status, response = insert_request.next_chunk()

                if status:
                    progress = int(status.progress() * 100)
                    logger.info(f"   進捗: {progress}%")

            except HttpError as e:
                if e.resp.status in [500, 502, 503, 504]:
                    error = f"再試行可能エラー: {e}"
                    time.sleep(2 ** retry)
                    retry += 1
                    if retry > 5:
                        logger.error(f"リトライ上限到達: {error}")
                        return None
                else:
                    logger.error(f"致命的エラー: {e}")
                    return None

            except Exception as e:
                logger.error(f"アップロードエラー: {e}")
                return None

        if 'id' in response:
            return response['id']
        else:
            logger.error(f"レスポンスに動画IDがありません: {response}")
            return None

    def set_thumbnail(self, video_id: str, thumbnail_path: str) -> bool:
        """サムネイルを設定（2MB 超は自動圧縮）。

        Args:
            video_id: YouTube 動画ID
            thumbnail_path: サムネイル画像ファイルパス

        Returns:
            成功時 True。
        """
        self._ensure_service()

        try:
            thumbnail_file = self._compress_thumbnail(Path(thumbnail_path))

            self.youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_file)),
            ).execute()

            logger.info(f"サムネイル設定完了: {Path(thumbnail_path).name}")

            # 一時ファイルのクリーンアップ
            if thumbnail_file != Path(thumbnail_path) and thumbnail_file.exists():
                thumbnail_file.unlink()

            return True

        except Exception as e:
            logger.warning(f"サムネイル設定エラー: {e}")
            return False

    def _compress_thumbnail(self, thumbnail_path: Path, max_bytes: int = 2_097_152) -> Path:
        """サムネイルが max_bytes を超える場合、ffmpeg で JPEG 圧縮した一時ファイルを返す。"""
        if thumbnail_path.stat().st_size <= max_bytes:
            return thumbnail_path

        import subprocess
        import tempfile

        compressed = Path(tempfile.mktemp(suffix='.jpg'))
        for quality in [2, 5]:  # ffmpeg -qscale:v 2=高品質, 5=中品質
            subprocess.run(
                ['ffmpeg', '-y', '-i', str(thumbnail_path), '-qscale:v', str(quality), str(compressed)],
                capture_output=True,
            )
            if compressed.exists() and compressed.stat().st_size <= max_bytes:
                logger.info(
                    f"サムネイル圧縮(q{quality}): "
                    f"{thumbnail_path.stat().st_size / 1024:.0f}KB -> {compressed.stat().st_size / 1024:.0f}KB"
                )
                return compressed

        logger.warning(f"サムネイル圧縮後も {compressed.stat().st_size / 1024:.0f}KB — 上限超過")
        return thumbnail_path
