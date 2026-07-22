"""
YouTube Upload Core - 動画アップロード・サムネイル設定の共通コア機能

各アップローダー（``YouTubeAutoUploader`` / ``CollectionUploader`` 等）で重複していた
アップロードロジックを単一モジュールに集約。継承または委譲で利用する。
"""

import logging
import time
from pathlib import Path
from typing import Callable, Optional

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from youtube_automation.utils.exceptions import QuotaExhaustedError, UploadError, YouTubeAPIError
from youtube_automation.utils.upload_policy import (
    SESSION_EXPIRED_HTTP_STATUSES,
    RetryDecision,
    ThumbnailCompression,
)
from youtube_automation.utils.youtube_service import get_youtube

logger = logging.getLogger(__name__)


def _resume_session_from_persisted_uri(insert_request, resume_session_uri: str) -> None:
    """永続化済みの resumable upload session URI を `HttpRequest` に注入する。

    `_in_error_state = True` をセットすることで、次回の `next_chunk()` は
    空 PUT による server 側 progress 問い合わせから始まり、Google の
    resume プロトコル正規パスに乗る（googleapiclient/http.py:1023-1032 参照）。
    """
    insert_request.resumable_uri = resume_session_uri
    # googleapiclient resume プロトコル発火フラグ。http.py:1023 参照
    insert_request._in_error_state = True


def _parse_retry_after(resp) -> float | None:
    """httplib2 Response から Retry-After header（秒数）を抽出する。

    HTTP-date 形式や解析不能な値の場合は None を返し、呼び出し側で
    指数 backoff にフォールバックさせる。
    """
    raw = resp.get("retry-after") if resp is not None else None
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


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

    def upload_video(
        self,
        video_path: str,
        body: dict,
        thumbnail_path: Optional[str] = None,
        *,
        resume_session_uri: Optional[str] = None,
        on_session_uri_changed: Optional[Callable[[Optional[str]], None]] = None,
        on_upload_complete: Optional[Callable[[], None]] = None,
    ) -> Optional[str]:
        """動画をアップロードして video_id を返す。

        Args:
            video_path: 動画ファイルパス
            body: YouTube API リクエストボディ（snippet, status 等）
            thumbnail_path: サムネイルファイルパス（省略時はサムネイル設定をスキップ）
            resume_session_uri: 前回中断時の resumable upload session URI。
                指定時は新規 insert ではなく既存セッションへ再開接続する。
            on_session_uri_changed: session URI 変化時に呼ばれるコールバック。
                None を渡されたら session 失効を意味する（永続化先で URI を消す）。
            on_upload_complete: アップロード成功直後に呼ばれるコールバック。
                永続化先で URI をクリアするフックとして使用する。

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
                part=",".join(body.keys()),
                body=body,
                media_body=media,
            )

            if resume_session_uri is not None:
                _resume_session_from_persisted_uri(insert_request, resume_session_uri)

            video_id = self._resumable_upload(
                insert_request,
                video_file.name,
                on_session_uri_changed=on_session_uri_changed,
            )

            if video_id:
                logger.info(f"アップロード成功: {video_id}")

                if on_upload_complete is not None:
                    on_upload_complete()

                if thumbnail_path and Path(thumbnail_path).exists():
                    self.set_thumbnail(video_id, thumbnail_path)

                return video_id
            else:
                logger.error(f"アップロード失敗: {video_file.name}")
                return None

        except HttpError as e:
            raise YouTubeAPIError(f"動画アップロード API エラー: {e}", status_code=e.resp.status) from e
        except OSError as e:
            raise UploadError(f"ファイルアクセスエラー: {e}") from e

    def _resumable_upload(
        self,
        insert_request,
        filename: str,
        *,
        on_session_uri_changed: Optional[Callable[[Optional[str]], None]] = None,
    ) -> Optional[str]:
        """再開可能アップロード実行（リトライ付き）。

        Args:
            insert_request: YouTube API リクエスト
            filename: ファイル名（ログ表示用）
            on_session_uri_changed: session URI 変化時のコールバック。
                None 値で発火すると「失効でクリア」を意味する。

        Returns:
            動画ID。失敗時は None。
        """
        response = None
        attempt = 0
        last_notified_uri: Optional[str] = getattr(insert_request, "resumable_uri", None)

        while response is None:
            try:
                logger.info(f"アップロード中: {filename} (試行{attempt + 1})")
                status, response = insert_request.next_chunk()

                if status:
                    progress = int(status.progress() * 100)
                    logger.info(f"   進捗: {progress}%")

                current_uri = getattr(insert_request, "resumable_uri", None)
                if on_session_uri_changed is not None and current_uri is not None and current_uri != last_notified_uri:
                    on_session_uri_changed(current_uri)
                    last_notified_uri = current_uri

            except HttpError as e:
                status_code = e.resp.status
                if status_code in SESSION_EXPIRED_HTTP_STATUSES:
                    logger.error(f"resumable session 失効: {e}")
                    if on_session_uri_changed is not None:
                        on_session_uri_changed(None)
                    return None

                retry_after = _parse_retry_after(e.resp)
                decision = RetryDecision.for_http_error(status_code, attempt, retry_after_seconds=retry_after)
                if decision.should_retry:
                    logger.warning(f"再試行可能エラー (HTTP {status_code}, 待機 {decision.delay_seconds}s): {e}")
                    time.sleep(decision.delay_seconds)
                    attempt += 1
                elif status_code == 429:
                    raise QuotaExhaustedError(
                        f"YouTube API の quota 超過/レート制限。時間をおいて再実行してください: {e}",
                        retry_after_seconds=retry_after,
                    ) from e
                else:
                    logger.error(f"致命的エラー: {e}")
                    return None

            except OSError as e:
                raise UploadError(f"アップロードエラー: {e}") from e

        if "id" in response:
            return response["id"]
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

        except HttpError as e:
            raise YouTubeAPIError(f"サムネイル設定 API エラー: {e}", status_code=e.resp.status) from e
        except OSError as e:
            logger.warning(f"サムネイル設定エラー: {e}")
            return False

    def _compress_thumbnail(self, thumbnail_path: Path, max_bytes: int = 2_097_152) -> Path:
        """サムネイルが max_bytes を超える場合、ffmpeg で JPEG 圧縮した一時ファイルを返す。"""
        strategy = ThumbnailCompression.for_file(thumbnail_path.stat().st_size, max_bytes)
        if not strategy.needs_compression:
            return thumbnail_path

        import subprocess
        import tempfile

        tmp_fd = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp_fd.close()
        compressed = Path(tmp_fd.name)
        failed_qualities: set[int] = set()

        while (quality := strategy.next_quality(failed_qualities)) is not None:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(thumbnail_path.resolve()), "-qscale:v", str(quality), str(compressed)],
                capture_output=True,
            )
            if compressed.exists() and compressed.stat().st_size <= max_bytes:
                logger.info(
                    f"サムネイル圧縮(q{quality}): "
                    f"{thumbnail_path.stat().st_size / 1024:.0f}KB -> {compressed.stat().st_size / 1024:.0f}KB"
                )
                return compressed
            failed_qualities.add(quality)

        if compressed.exists():
            logger.warning(
                f"サムネイル圧縮後も {compressed.stat().st_size / 1024:.0f}KB — 上限超過、"
                f"元ファイル({thumbnail_path.stat().st_size / 1024:.0f}KB)のまま試行"
            )
            compressed.unlink(missing_ok=True)
        else:
            logger.warning(f"サムネイル圧縮失敗、元ファイル({thumbnail_path.stat().st_size / 1024:.0f}KB)のまま試行")
        return thumbnail_path
