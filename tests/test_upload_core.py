"""
YouTubeUploadCore のユニットテスト

テスト対象: utils/upload_core.py
YouTube API 呼び出しを unittest.mock でモック化して検証する。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------

@pytest.fixture
def upload_core():
    """YouTubeUploadCore インスタンスを返す（youtube_service をモック）"""
    with patch('utils.upload_core.get_youtube') as mock_get_youtube:
        mock_get_youtube.return_value = MagicMock()
        from utils.upload_core import YouTubeUploadCore
        core = YouTubeUploadCore()
        yield core


@pytest.fixture
def initialized_core(upload_core):
    """initialize() 済みの YouTubeUploadCore を返す"""
    with patch('utils.upload_core.get_youtube') as mock_get_youtube:
        mock_youtube = MagicMock()
        mock_get_youtube.return_value = mock_youtube
        upload_core.initialize()
        assert upload_core.youtube is mock_youtube
        yield upload_core


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------

class TestInitialize:
    @patch('utils.upload_core.get_youtube')
    def test_sets_youtube_service(self, mock_get_youtube):
        from utils.upload_core import YouTubeUploadCore
        mock_service = MagicMock()
        mock_get_youtube.return_value = mock_service

        core = YouTubeUploadCore()
        assert core.youtube is None
        core.initialize()
        assert core.youtube is mock_service


# ---------------------------------------------------------------------------
# _compress_thumbnail
# ---------------------------------------------------------------------------

class TestCompressThumbnail:
    def test_returns_original_when_under_limit(self, tmp_path, upload_core):
        thumb = tmp_path / "small.jpg"
        thumb.write_bytes(b"x" * 1000)  # well under 2MB

        result = upload_core._compress_thumbnail(thumb)
        assert result == thumb

    @patch('subprocess.run')
    def test_calls_ffmpeg_when_over_limit(self, mock_run, tmp_path, upload_core):
        thumb = tmp_path / "large.jpg"
        thumb.write_bytes(b"x" * 3_000_000)  # over 2MB

        # Simulate ffmpeg creating a compressed file
        def fake_ffmpeg(*args, **kwargs):
            cmd = args[0]
            output_path = Path(cmd[-1])
            output_path.write_bytes(b"x" * 1_500_000)  # under 2MB
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        result = upload_core._compress_thumbnail(thumb)

        assert result != thumb
        assert result.suffix == ".jpg"
        # First call with quality 2
        first_call = mock_run.call_args_list[0]
        assert '-qscale:v' in first_call[0][0]
        assert '2' in first_call[0][0]

    @patch('subprocess.run')
    def test_tries_quality_5_if_quality_2_still_large(self, mock_run, tmp_path, upload_core):
        thumb = tmp_path / "huge.jpg"
        thumb.write_bytes(b"x" * 4_000_000)

        call_count = [0]

        def fake_ffmpeg(*args, **kwargs):
            cmd = args[0]
            output_path = Path(cmd[-1])
            call_count[0] += 1
            if call_count[0] == 1:
                # q2: still too large
                output_path.write_bytes(b"x" * 2_500_000)
            else:
                # q5: small enough
                output_path.write_bytes(b"x" * 1_500_000)
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        result = upload_core._compress_thumbnail(thumb)
        assert mock_run.call_count == 2
        assert result.suffix == ".jpg"

    @patch('subprocess.run')
    def test_returns_original_if_compression_fails(self, mock_run, tmp_path, upload_core):
        thumb = tmp_path / "huge.jpg"
        thumb.write_bytes(b"x" * 4_000_000)

        def fake_ffmpeg(*args, **kwargs):
            cmd = args[0]
            output_path = Path(cmd[-1])
            # Always too large
            output_path.write_bytes(b"x" * 3_000_000)
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        result = upload_core._compress_thumbnail(thumb)
        assert result == thumb  # falls back to original


# ---------------------------------------------------------------------------
# set_thumbnail
# ---------------------------------------------------------------------------

class TestSetThumbnail:
    def test_sets_thumbnail_successfully(self, tmp_path, initialized_core):
        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"x" * 1000)

        mock_thumbnails = MagicMock()
        initialized_core.youtube.thumbnails.return_value = mock_thumbnails
        mock_thumbnails.set.return_value.execute.return_value = {}

        result = initialized_core.set_thumbnail("video123", str(thumb))
        assert result is True
        mock_thumbnails.set.assert_called_once()

    def test_returns_false_on_error(self, tmp_path, initialized_core):
        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"x" * 1000)

        initialized_core.youtube.thumbnails.side_effect = Exception("API error")

        result = initialized_core.set_thumbnail("video123", str(thumb))
        assert result is False


# ---------------------------------------------------------------------------
# _resumable_upload
# ---------------------------------------------------------------------------

class TestResumableUpload:
    def test_successful_upload(self, upload_core):
        mock_request = MagicMock()
        mock_request.next_chunk.return_value = (None, {'id': 'abc123'})

        result = upload_core._resumable_upload(mock_request, "test.mp4")
        assert result == "abc123"

    def test_upload_with_progress(self, upload_core):
        mock_status = MagicMock()
        mock_status.progress.return_value = 0.5

        mock_request = MagicMock()
        mock_request.next_chunk.side_effect = [
            (mock_status, None),  # 50% progress, not done
            (None, {'id': 'xyz789'}),  # done
        ]

        result = upload_core._resumable_upload(mock_request, "test.mp4")
        assert result == "xyz789"
        assert mock_request.next_chunk.call_count == 2

    def test_retries_on_5xx_error(self, upload_core):
        resp = Response({'status': 503})
        error = HttpError(resp, b"Service Unavailable")

        mock_request = MagicMock()
        mock_request.next_chunk.side_effect = [
            error,
            (None, {'id': 'retry_ok'}),
        ]

        with patch('utils.upload_core.time.sleep'):
            result = upload_core._resumable_upload(mock_request, "test.mp4")

        assert result == "retry_ok"

    def test_gives_up_after_max_retries(self, upload_core):
        resp = Response({'status': 500})
        error = HttpError(resp, b"Internal Server Error")

        mock_request = MagicMock()
        mock_request.next_chunk.side_effect = error  # always fails

        with patch('utils.upload_core.time.sleep'):
            result = upload_core._resumable_upload(mock_request, "test.mp4")

        assert result is None
        # 6 attempts: initial + 5 retries (retry > 5 triggers exit)
        assert mock_request.next_chunk.call_count == 6

    def test_non_retryable_error_returns_none(self, upload_core):
        resp = Response({'status': 403})
        error = HttpError(resp, b"Forbidden")

        mock_request = MagicMock()
        mock_request.next_chunk.side_effect = error

        result = upload_core._resumable_upload(mock_request, "test.mp4")
        assert result is None
        mock_request.next_chunk.assert_called_once()

    def test_generic_exception_returns_none(self, upload_core):
        mock_request = MagicMock()
        mock_request.next_chunk.side_effect = RuntimeError("network error")

        result = upload_core._resumable_upload(mock_request, "test.mp4")
        assert result is None

    def test_response_without_id_returns_none(self, upload_core):
        mock_request = MagicMock()
        mock_request.next_chunk.return_value = (None, {'status': 'ok'})

        result = upload_core._resumable_upload(mock_request, "test.mp4")
        assert result is None
