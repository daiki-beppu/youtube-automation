"""YouTubeAutoUploader のユニットテスト

テスト対象: `youtube_automation.agents.youtube_auto_uploader.YouTubeAutoUploader`

issue #381 (P0-5) で追加される以下の振る舞いを検証する:

1. resume kwargs (`resume_session_uri`, `on_session_uri_changed`, `on_upload_complete`)
   が `upload_video` / `upload_collection` / `_upload_complete_collection` を透過して
   `YouTubeUploadCore.upload_video` まで届くこと
2. `_find_existing_video_by_title` が own channel 内の同タイトル動画を検出すること
   （fail-open: HttpError 時は None を返して upload 続行を許す）
3. `_upload_complete_collection` が publish 直前に dedup 検索を実行し、hit 時は
   `upload_video` を呼ばずに既存 video_id / video_url を採用すること
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from googleapiclient.errors import HttpError
from httplib2 import Response

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


_SESS_PREV = "https://upload.googleapis.com/SESS_PREV"


def _make_http_error(status: int, message: bytes = b"error") -> HttpError:
    resp = Response({"status": status})
    return HttpError(resp, message)


def _make_metadata(title: str = "Rainy Jazz") -> dict:
    """`upload_video` (YouTubeAutoUploader 版) が受理するメタデータ最小セット."""
    return {
        "title": title,
        "description": "desc",
        "tags": ["t1"],
        "category_id": "10",
        "language": "en",
        "privacy_status": "private",
    }


# ---------------------------------------------------------------------------
# L3a: kwargs パススルー — upload_video → YouTubeUploadCore.upload_video
# ---------------------------------------------------------------------------


class TestUploadVideoForwarding:
    """`YouTubeAutoUploader.upload_video` が resume kwargs をコアへ透過する."""

    def test_should_forward_resume_kwargs_to_core_upload_video(self, tmp_path):
        """resume kwargs 3 種が `super().upload_video()` に転送される."""
        # Given
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        uploader = YouTubeAutoUploader(collections_root=str(tmp_path / "collections"))
        video = tmp_path / "v.mp4"
        video.write_bytes(b"\x00")

        on_session = MagicMock()
        on_complete = MagicMock()

        with patch(
            "youtube_automation.agents.youtube_auto_uploader.YouTubeUploadCore.upload_video",
            return_value="VID_FORWARDED",
        ) as mock_core_upload:
            # When
            result = uploader.upload_video(
                str(video),
                _make_metadata(),
                thumbnail_path=None,
                resume_session_uri=_SESS_PREV,
                on_session_uri_changed=on_session,
                on_upload_complete=on_complete,
            )

        # Then
        assert result == "VID_FORWARDED"
        call_kwargs = mock_core_upload.call_args.kwargs
        assert call_kwargs.get("resume_session_uri") == _SESS_PREV
        assert call_kwargs.get("on_session_uri_changed") is on_session
        assert call_kwargs.get("on_upload_complete") is on_complete

    def test_should_default_resume_kwargs_to_none_when_omitted(self, tmp_path):
        """resume kwargs を渡さなければコアにも None 相当が渡る（後方互換）."""
        # Given
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        uploader = YouTubeAutoUploader(collections_root=str(tmp_path / "collections"))
        video = tmp_path / "v.mp4"
        video.write_bytes(b"\x00")

        with patch(
            "youtube_automation.agents.youtube_auto_uploader.YouTubeUploadCore.upload_video",
            return_value="VID_DEFAULT",
        ) as mock_core_upload:
            # When
            uploader.upload_video(str(video), _make_metadata())

        # Then: 旧署名互換 — kwargs を渡しても None、または kwargs に含まれず default が効く
        call_kwargs = mock_core_upload.call_args.kwargs
        assert call_kwargs.get("resume_session_uri") is None
        assert call_kwargs.get("on_session_uri_changed") is None
        assert call_kwargs.get("on_upload_complete") is None


# ---------------------------------------------------------------------------
# L3a: kwargs パススルー — upload_collection → _upload_complete_collection → upload_video
# ---------------------------------------------------------------------------


class TestUploadCollectionForwarding:
    """`upload_collection` が resume kwargs を `_upload_complete_collection` まで透過."""

    def test_should_forward_resume_kwargs_through_to_upload_complete_collection(self, tmp_path):
        """`upload_collection(...)` の kwargs が `_upload_complete_collection` に届く."""
        # Given
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        col_dir = tmp_path / "20990101-foo-collection"
        col_dir.mkdir(parents=True)

        uploader = YouTubeAutoUploader(collections_root=str(tmp_path))
        on_session = MagicMock()
        on_complete = MagicMock()

        with (
            patch.object(uploader, "_preflight_check"),
            patch.object(
                uploader,
                "_upload_complete_collection",
                return_value={"video_id": "V", "video_url": "u", "title": "t", "file_path": "p"},
            ) as mock_inner,
            patch("youtube_automation.agents.youtube_auto_uploader.BAHMetadataGenerator") as mock_gen_cls,
        ):
            mock_gen_cls.return_value.collection_name = col_dir.name

            # When
            uploader.upload_collection(
                str(col_dir),
                publish_at=None,
                resume_session_uri=_SESS_PREV,
                on_session_uri_changed=on_session,
                on_upload_complete=on_complete,
            )

        # Then
        call_kwargs = mock_inner.call_args.kwargs
        assert call_kwargs.get("resume_session_uri") == _SESS_PREV
        assert call_kwargs.get("on_session_uri_changed") is on_session
        assert call_kwargs.get("on_upload_complete") is on_complete

    def test_should_forward_resume_kwargs_from_complete_collection_to_upload_video(self, tmp_path):
        """`_upload_complete_collection` が `self.upload_video` に resume kwargs を渡す."""
        # Given
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        col_dir = tmp_path / "20990101-foo-collection"
        master_dir = col_dir / "01-master"
        master_dir.mkdir(parents=True)
        (master_dir / "video.mp4").write_bytes(b"\x00")

        uploader = YouTubeAutoUploader(collections_root=str(tmp_path))
        on_session = MagicMock()
        on_complete = MagicMock()

        mock_gen = MagicMock()
        mock_gen.generate_complete_collection_metadata.return_value = _make_metadata()

        with (
            patch.object(uploader, "_load_descriptions_md", return_value=None),
            patch.object(uploader, "_find_existing_video_by_title", return_value=None),
            patch.object(uploader, "upload_video", return_value="VID_INNER") as mock_upload_video,
        ):
            # When
            uploader._upload_complete_collection(
                col_dir,
                mock_gen,
                publish_at=None,
                resume_session_uri=_SESS_PREV,
                on_session_uri_changed=on_session,
                on_upload_complete=on_complete,
            )

        # Then
        call_kwargs = mock_upload_video.call_args.kwargs
        assert call_kwargs.get("resume_session_uri") == _SESS_PREV
        assert call_kwargs.get("on_session_uri_changed") is on_session
        assert call_kwargs.get("on_upload_complete") is on_complete


# ---------------------------------------------------------------------------
# L3b: `_find_existing_video_by_title` 単体検証
# ---------------------------------------------------------------------------


class TestFindExistingVideoByTitle:
    """publish 直前の同タイトル検索（dedup 安全網）の振る舞い."""

    def _make_uploader_with_mock_youtube(self, tmp_path):
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        uploader = YouTubeAutoUploader(collections_root=str(tmp_path))
        mock_youtube = MagicMock()
        # _ensure_service / initialize を bypass
        uploader.youtube = mock_youtube
        return uploader, mock_youtube

    def test_should_return_video_info_when_exact_title_match_exists(self, tmp_path):
        """plan 要件 #8 + #9: 完全一致 hit で video_id / video_url を返す."""
        # Given
        uploader, mock_youtube = self._make_uploader_with_mock_youtube(tmp_path)
        mock_youtube.search.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": {"videoId": "v9"}, "snippet": {"title": "Rainy Jazz"}},
            ]
        }

        # When
        result = uploader._find_existing_video_by_title("Rainy Jazz")

        # Then
        assert result == {
            "video_id": "v9",
            "video_url": "https://www.youtube.com/watch?v=v9",
        }

    def test_should_call_youtube_search_with_for_mine_true_type_video(self, tmp_path):
        """plan 要件 #8: search API は forMine=True / type=video / q=title で叩く."""
        # Given
        uploader, mock_youtube = self._make_uploader_with_mock_youtube(tmp_path)
        mock_youtube.search.return_value.list.return_value.execute.return_value = {"items": []}

        # When
        uploader._find_existing_video_by_title("Rainy Jazz")

        # Then
        mock_youtube.search.return_value.list.assert_called_once()
        call_kwargs = mock_youtube.search.return_value.list.call_args.kwargs
        assert call_kwargs.get("forMine") is True
        assert call_kwargs.get("type") == "video"
        assert call_kwargs.get("q") == "Rainy Jazz"
        assert call_kwargs.get("maxResults") == 10
        assert call_kwargs.get("part") == "snippet"

    def test_should_return_none_when_only_partial_title_matches_found(self, tmp_path):
        """plan §149: 完全一致のみ採用。部分一致は None を返す."""
        # Given
        uploader, mock_youtube = self._make_uploader_with_mock_youtube(tmp_path)
        mock_youtube.search.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": {"videoId": "v_other"}, "snippet": {"title": "Rainy Jazz Live"}},
            ]
        }

        # When
        result = uploader._find_existing_video_by_title("Rainy Jazz")

        # Then
        assert result is None

    def test_should_return_none_when_search_returns_empty_items(self, tmp_path):
        """検索結果が空なら None を返す."""
        # Given
        uploader, mock_youtube = self._make_uploader_with_mock_youtube(tmp_path)
        mock_youtube.search.return_value.list.return_value.execute.return_value = {"items": []}

        # When
        result = uploader._find_existing_video_by_title("Rainy Jazz")

        # Then
        assert result is None

    def test_should_fail_open_and_return_none_on_http_error(self, tmp_path, caplog):
        """plan 要件 #10: search API エラーは fail-open（warning + None 返却）."""
        # Given
        uploader, mock_youtube = self._make_uploader_with_mock_youtube(tmp_path)
        mock_youtube.search.return_value.list.return_value.execute.side_effect = _make_http_error(500)

        # When
        with caplog.at_level(logging.WARNING):
            result = uploader._find_existing_video_by_title("Rainy Jazz")

        # Then
        assert result is None
        # warning が出ていること（メッセージ本文の厳密一致は強制しない）
        assert any(rec.levelno == logging.WARNING for rec in caplog.records)


# ---------------------------------------------------------------------------
# L3b: `_upload_complete_collection` の dedup 配線
# ---------------------------------------------------------------------------


class TestUploadCompleteCollectionDedup:
    """publish 直前 dedup の skip / proceed / fail-open 分岐."""

    def _setup(self, tmp_path):
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        col_dir = tmp_path / "20990101-foo-collection"
        master_dir = col_dir / "01-master"
        master_dir.mkdir(parents=True)
        (master_dir / "video.mp4").write_bytes(b"\x00")

        uploader = YouTubeAutoUploader(collections_root=str(tmp_path))
        mock_gen = MagicMock()
        mock_gen.generate_complete_collection_metadata.return_value = _make_metadata("Rainy Jazz")
        return uploader, col_dir, mock_gen

    def test_should_skip_upload_when_dedup_search_hits(self, tmp_path):
        """plan 要件 #9: dedup hit 時は `upload_video` を呼ばず既存 video_id を採用."""
        # Given
        uploader, col_dir, mock_gen = self._setup(tmp_path)
        existing = {"video_id": "v9", "video_url": "https://www.youtube.com/watch?v=v9"}

        with (
            patch.object(uploader, "_load_descriptions_md", return_value=None),
            patch.object(uploader, "_find_existing_video_by_title", return_value=existing),
            patch.object(uploader, "upload_video", return_value="SHOULD_NOT_BE_CALLED") as mock_upload_video,
        ):
            # When
            result = uploader._upload_complete_collection(col_dir, mock_gen, publish_at=None)

        # Then: upload_video は呼ばれず、既存 video_id を返す
        mock_upload_video.assert_not_called()
        assert result["video_id"] == "v9"
        assert result["video_url"] == "https://www.youtube.com/watch?v=v9"

    def test_should_proceed_with_upload_when_dedup_search_returns_none(self, tmp_path):
        """dedup miss 時は通常通り `upload_video` を呼ぶ."""
        # Given
        uploader, col_dir, mock_gen = self._setup(tmp_path)

        with (
            patch.object(uploader, "_load_descriptions_md", return_value=None),
            patch.object(uploader, "_find_existing_video_by_title", return_value=None),
            patch.object(uploader, "upload_video", return_value="VID_NEW") as mock_upload_video,
        ):
            # When
            result = uploader._upload_complete_collection(col_dir, mock_gen, publish_at=None)

        # Then
        mock_upload_video.assert_called_once()
        assert result["video_id"] == "VID_NEW"

    def test_should_proceed_with_upload_when_search_api_raises_http_error(self, tmp_path, caplog):
        """plan 要件 #10: search API 自体が HttpError を投げたケースで fail-open で upload 続行."""
        # Given
        uploader, col_dir, mock_gen = self._setup(tmp_path)

        # 実 youtube.search を HttpError で失敗させ、`_find_existing_video_by_title`
        # の fail-open 経路（HttpError → warning + None 返却）を実コードで通す
        mock_youtube = MagicMock()
        mock_youtube.search.return_value.list.return_value.execute.side_effect = (
            _make_http_error(500)
        )
        uploader.youtube = mock_youtube

        with (
            patch.object(uploader, "_load_descriptions_md", return_value=None),
            patch.object(uploader, "upload_video", return_value="VID_AFTER_FAILOPEN") as mock_upload_video,
            caplog.at_level(logging.WARNING),
        ):
            # When
            result = uploader._upload_complete_collection(col_dir, mock_gen, publish_at=None)

        # Then: search API 失敗を warning で記録した上で upload は続行する
        mock_youtube.search.return_value.list.assert_called_once()
        mock_upload_video.assert_called_once()
        assert result["video_id"] == "VID_AFTER_FAILOPEN"
        assert any(rec.levelno == logging.WARNING for rec in caplog.records)
