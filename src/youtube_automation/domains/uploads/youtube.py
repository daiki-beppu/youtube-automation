"""Canonical public owner of resumable YouTube uploads."""

import logging
import time
from pathlib import Path
from typing import Callable, Optional

from youtube_automation.core.errors import (
    QuotaExhaustedError,
    UploadError,
    YouTubeAPIError,
)
from youtube_automation.domains.uploads.policy import SESSION_EXPIRED_HTTP_STATUSES, RetryDecision, ThumbnailCompression
from youtube_automation.infrastructure.filesystem import file_size, path_exists, remove_file
from youtube_automation.infrastructure.google.upload import HttpError, create_media_upload
from youtube_automation.infrastructure.google.youtube import (
    execute_youtube_request,
)
from youtube_automation.infrastructure.process import compress_image

logger = logging.getLogger(__name__)


def _resume_session_from_persisted_uri(insert_request, resume_session_uri: str) -> None:
    insert_request.resumable_uri = resume_session_uri
    insert_request._in_error_state = True


def _parse_retry_after(resp) -> float | None:
    raw = resp.get("retry-after") if resp is not None else None
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _compress_thumbnail_file(thumbnail_path: Path, max_bytes: int) -> Path:
    """Apply thumbnail size and quality policy independently of the upload service."""
    strategy = ThumbnailCompression.for_file(file_size(thumbnail_path), max_bytes)
    if not strategy.needs_compression:
        return thumbnail_path
    failed_qualities: set[int] = set()
    while (quality := strategy.next_quality(failed_qualities)) is not None:
        compressed = compress_image(thumbnail_path, [quality], max_bytes)
        if compressed != thumbnail_path:
            return compressed
        failed_qualities.add(quality)
    return thumbnail_path


def _run_resumable_upload(
    insert_request, *, on_session_uri_changed: Optional[Callable[[Optional[str]], None]] = None
) -> Optional[str]:
    """Drive one resumable request with session notifications and bounded retry policy."""
    response = None
    attempt = 0
    last_uri = getattr(insert_request, "resumable_uri", None)
    while response is None:
        try:
            _status, response = insert_request.next_chunk()
            current_uri = getattr(insert_request, "resumable_uri", None)
            if on_session_uri_changed and current_uri is not None and current_uri != last_uri:
                on_session_uri_changed(current_uri)
                last_uri = current_uri
        except HttpError as e:
            status_code = e.resp.status
            if status_code in SESSION_EXPIRED_HTTP_STATUSES:
                if on_session_uri_changed:
                    on_session_uri_changed(None)
                return None
            retry_after = _parse_retry_after(e.resp)
            decision = RetryDecision.for_http_error(status_code, attempt, retry_after_seconds=retry_after)
            if decision.should_retry:
                time.sleep(decision.delay_seconds)
                attempt += 1
            elif status_code == 429:
                raise QuotaExhaustedError(
                    "YouTube API の quota 超過/レート制限。時間をおいて再実行してください",
                    retry_after_seconds=retry_after,
                ) from e
            else:
                return None
        except OSError as e:
            raise UploadError(f"アップロードエラー: {e}") from e
    return response.get("id") if "id" in response else None


class ResumableUploader:
    """Common resumable upload and thumbnail operations."""

    def __init__(self, youtube_clients):
        self.youtube = None
        self.youtube_clients = youtube_clients

    def initialize(self):
        if self.youtube_clients is None:
            raise TypeError("youtube_clients is required")
        self.youtube = self.youtube_clients.youtube

    def _ensure_service(self):
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
        self._ensure_service()
        video_file = Path(video_path)
        if not path_exists(video_file):
            return None
        try:
            request = self.youtube.videos().insert(
                part=",".join(body.keys()),
                body=body,
                media_body=create_media_upload(str(video_file), chunksize=-1, resumable=True),
            )
            if resume_session_uri is not None:
                _resume_session_from_persisted_uri(request, resume_session_uri)
            video_id = self._resumable_upload(request, video_file.name, on_session_uri_changed=on_session_uri_changed)
            if video_id and on_upload_complete is not None:
                on_upload_complete()
            if video_id and thumbnail_path and path_exists(Path(thumbnail_path)):
                self.set_thumbnail(video_id, thumbnail_path)
            return video_id
        except HttpError as e:
            raise YouTubeAPIError(f"動画アップロード API エラー: {e}", status_code=e.resp.status) from e
        except OSError as e:
            raise UploadError(f"ファイルアクセスエラー: {e}") from e

    def _resumable_upload(
        self, insert_request, filename: str, *, on_session_uri_changed: Optional[Callable[[Optional[str]], None]] = None
    ) -> Optional[str]:
        return _run_resumable_upload(insert_request, on_session_uri_changed=on_session_uri_changed)

    def set_thumbnail(self, video_id: str, thumbnail_path: str) -> bool:
        self._ensure_service()
        try:
            thumbnail_file = self._compress_thumbnail(Path(thumbnail_path))
            execute_youtube_request(
                self.youtube.thumbnails().set(videoId=video_id, media_body=create_media_upload(str(thumbnail_file))),
                "thumbnails.set failed",
            )
            if thumbnail_file != Path(thumbnail_path) and path_exists(thumbnail_file):
                remove_file(thumbnail_file)
            return True
        except HttpError as e:
            raise YouTubeAPIError(f"サムネイル設定 API エラー: {e}", status_code=e.resp.status) from e
        except OSError:
            return False

    def _compress_thumbnail(self, thumbnail_path: Path, max_bytes: int = 2_097_152) -> Path:
        return _compress_thumbnail_file(thumbnail_path, max_bytes)


__all__ = ["ResumableUploader"]
