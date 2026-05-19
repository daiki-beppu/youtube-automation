"""YouTubeUploadCore の統合テスト（Khorikov 準拠）

公開 API（upload_video, set_thumbnail）の振る舞いを検証する。
mock は管理下にない依存（YouTube API）にのみ使用。
プライベートメソッドの直接テストは行わない。
"""

from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from youtube_automation.utils.exceptions import QuotaExhaustedError, UploadError, YouTubeAPIError

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _make_core_with_mock_youtube():
    """YouTube API を mock した YouTubeUploadCore を返す。"""
    with patch("youtube_automation.utils.upload_core.get_youtube") as mock_get_youtube:
        mock_youtube = MagicMock()
        mock_get_youtube.return_value = mock_youtube

        from youtube_automation.utils.upload_core import YouTubeUploadCore

        core = YouTubeUploadCore()
        core.initialize()

        return core, mock_youtube


def _make_http_error(
    status: int,
    message: bytes = b"error",
    retry_after: str | None = None,
) -> HttpError:
    """指定ステータスの HttpError を生成する。"""
    info: dict = {"status": status}
    if retry_after is not None:
        info["retry-after"] = retry_after
    resp = Response(info)
    return HttpError(resp, message)


# ---------------------------------------------------------------------------
# upload_video: 動画アップロード
# ---------------------------------------------------------------------------


class TestUploadVideo:
    def test_uploads_video_and_returns_id(self, tmp_path):
        """ハッピーパス: 動画アップロードが成功し video_id を返す"""
        core, mock_youtube = _make_core_with_mock_youtube()

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")

        mock_insert = MagicMock()
        mock_youtube.videos.return_value.insert.return_value = mock_insert
        mock_insert.next_chunk.return_value = (None, {"id": "abc123"})

        result = core.upload_video(str(video), {"snippet": {}, "status": {}})

        assert result == "abc123"

    def test_returns_none_for_missing_file(self):
        """存在しないファイルを指定すると None を返す"""
        core, _ = _make_core_with_mock_youtube()

        result = core.upload_video("/nonexistent/video.mp4", {"snippet": {}})

        assert result is None

    def test_raises_api_error_on_http_error(self, tmp_path):
        """YouTube API の HttpError は YouTubeAPIError に変換される"""
        core, mock_youtube = _make_core_with_mock_youtube()

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")

        mock_youtube.videos.return_value.insert.side_effect = _make_http_error(403)

        with pytest.raises(YouTubeAPIError):
            core.upload_video(str(video), {"snippet": {}})

    def test_raises_upload_error_on_os_error(self, tmp_path):
        """ファイルアクセスエラーは UploadError に変換される"""
        core, mock_youtube = _make_core_with_mock_youtube()

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")

        mock_insert = MagicMock()
        mock_youtube.videos.return_value.insert.return_value = mock_insert
        mock_insert.next_chunk.side_effect = OSError("disk error")

        with pytest.raises(UploadError):
            core.upload_video(str(video), {"snippet": {}})


# ---------------------------------------------------------------------------
# set_thumbnail: サムネイル設定
# ---------------------------------------------------------------------------


class TestSetThumbnail:
    def test_sets_thumbnail_for_small_image(self, tmp_path):
        """2MB 以下の画像はそのままアップロードされ True を返す"""
        core, mock_youtube = _make_core_with_mock_youtube()

        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"x" * 1000)

        mock_youtube.thumbnails.return_value.set.return_value.execute.return_value = {}

        result = core.set_thumbnail("video123", str(thumb))

        assert result is True

    def test_returns_false_when_file_inaccessible(self):
        """ファイルアクセスエラー時は False を返す"""
        core, mock_youtube = _make_core_with_mock_youtube()

        mock_youtube.thumbnails.return_value.set.return_value.execute.side_effect = OSError("disk")

        # OSError は set_thumbnail 内で catch され False を返す
        result = core.set_thumbnail("video123", "/nonexistent/thumb.jpg")

        assert result is False

    def test_raises_api_error_on_http_error(self, tmp_path):
        """YouTube API エラーは YouTubeAPIError に変換される"""
        core, mock_youtube = _make_core_with_mock_youtube()

        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"x" * 1000)

        mock_youtube.thumbnails.return_value.set.return_value.execute.side_effect = _make_http_error(403)

        with pytest.raises(YouTubeAPIError):
            core.set_thumbnail("video123", str(thumb))


# ---------------------------------------------------------------------------
# リトライ動作: 公開メソッド upload_video 経由で検証
# ---------------------------------------------------------------------------


class TestRetryBehavior:
    def test_retries_and_succeeds_on_transient_server_error(self, tmp_path):
        """5xx エラー後にリトライし、最終的に成功する"""
        core, mock_youtube = _make_core_with_mock_youtube()

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")

        mock_insert = MagicMock()
        mock_youtube.videos.return_value.insert.return_value = mock_insert
        mock_insert.next_chunk.side_effect = [
            _make_http_error(503),
            (None, {"id": "retry_ok"}),
        ]

        with patch("youtube_automation.utils.upload_core.time.sleep"):
            result = core.upload_video(str(video), {"snippet": {}})

        assert result == "retry_ok"

    def test_retries_on_rate_limit_and_succeeds(self, tmp_path):
        """429 エラー後にリトライし、最終的に成功する"""
        core, mock_youtube = _make_core_with_mock_youtube()

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")

        mock_insert = MagicMock()
        mock_youtube.videos.return_value.insert.return_value = mock_insert
        mock_insert.next_chunk.side_effect = [
            _make_http_error(429),
            (None, {"id": "rate_limited_then_ok"}),
        ]

        with patch("youtube_automation.utils.upload_core.time.sleep"):
            result = core.upload_video(str(video), {"snippet": {}})

        assert result == "rate_limited_then_ok"

    def test_honors_retry_after_header_on_rate_limit(self, tmp_path):
        """Retry-After header の秒数を sleep に渡す"""
        core, mock_youtube = _make_core_with_mock_youtube()

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")

        mock_insert = MagicMock()
        mock_youtube.videos.return_value.insert.return_value = mock_insert
        mock_insert.next_chunk.side_effect = [
            _make_http_error(429, retry_after="12"),
            (None, {"id": "after_wait"}),
        ]

        with patch("youtube_automation.utils.upload_core.time.sleep") as mock_sleep:
            result = core.upload_video(str(video), {"snippet": {}})

        assert result == "after_wait"
        mock_sleep.assert_called_once_with(12.0)

    def test_raises_quota_exhausted_after_max_retries(self, tmp_path):
        """429 リトライ枯渇時は QuotaExhaustedError を raise する"""
        core, mock_youtube = _make_core_with_mock_youtube()

        video = tmp_path / "test.mp4"
        video.write_bytes(b"video content")

        mock_insert = MagicMock()
        mock_youtube.videos.return_value.insert.return_value = mock_insert
        # MAX_RETRY_ATTEMPTS=5 → attempt 0..4 でリトライ、attempt=5 で枯渇
        # 合計 6 回 429 を返せば必ず exhausted
        mock_insert.next_chunk.side_effect = [_make_http_error(429, retry_after="1")] * 6

        with patch("youtube_automation.utils.upload_core.time.sleep"):
            with pytest.raises(QuotaExhaustedError) as exc_info:
                core.upload_video(str(video), {"snippet": {}})

        assert exc_info.value.status_code == 429
        assert exc_info.value.retry_after_seconds == 1.0
