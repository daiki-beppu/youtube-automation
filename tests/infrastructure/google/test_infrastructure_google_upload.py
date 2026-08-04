"""Google upload SDK adapter の引数伝播テスト。"""

from __future__ import annotations

from unittest.mock import patch

from youtube_automation.infrastructure.google import upload


def test_create_media_upload_forwards_default_large_upload_options() -> None:
    with patch.object(upload, "MediaFileUpload", return_value="media") as media_factory:
        result = upload.create_media_upload("/videos/master.mp4")

    assert result == "media"
    media_factory.assert_called_once_with("/videos/master.mp4", chunksize=-1, resumable=True)


def test_create_media_upload_forwards_custom_chunk_and_resumable_options() -> None:
    with patch.object(upload, "MediaFileUpload", return_value="media") as media_factory:
        upload.create_media_upload("relative/video.mp4", chunksize=8 * 1024 * 1024, resumable=False)

    media_factory.assert_called_once_with(
        "relative/video.mp4",
        chunksize=8 * 1024 * 1024,
        resumable=False,
    )
