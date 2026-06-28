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

import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
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


def _make_preflight_config(supported_languages: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        audio=SimpleNamespace(
            chapter_max=100,
            target_duration_min=None,
            target_duration_max=None,
        ),
        content=SimpleNamespace(
            tags=SimpleNamespace(
                min_count=None,
                for_collection=lambda _name: ["fallback"],
            ),
            # ` | ` を使わない鋳型 → タイトル鋳型準拠チェックは自動スキップ (#602)
            title=SimpleNamespace(
                template="{style} {theme} for {activity}",
                template_check={},
            ),
        ),
        localizations=SimpleNamespace(supported_languages=supported_languages),
    )


def _write_preflight_collection(tmp_path: Path, scene_languages: list[str]) -> Path:
    col_dir = tmp_path / "20990101-foo-collection"
    doc_dir = col_dir / "20-documentation"
    doc_dir.mkdir(parents=True)
    (doc_dir / "descriptions.md").write_text(
        "\n".join(
            [
                "## タイトル案",
                "```",
                "Rainy Jazz for Focus",
                "```",
                "",
                "## Complete Collection 概要欄",
                "```",
                "00:00 Opening Rain",
                "10:00 Warm Desk Light",
                "20:00 Last Train Home",
                "```",
                "",
                "## タグ（YouTube タグ欄）",
                "```",
                "rainy jazz, focus music, night study",
                "```",
            ]
        ),
        encoding="utf-8",
    )
    scene_phrases = {lang: {"title": f"title-{lang}"} for lang in scene_languages}
    (col_dir / "workflow-state.json").write_text(
        json.dumps({"scene_phrases": scene_phrases}),
        encoding="utf-8",
    )
    return col_dir


# ---------------------------------------------------------------------------
# Issue #587: `_preflight_check` localization quality gates
# ---------------------------------------------------------------------------


class TestPreflightLocalizationLanguages:
    def test_should_pass_when_supported_scene_languages_are_present(self, tmp_path):
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        col_dir = _write_preflight_collection(tmp_path, ["en", "ja"])
        uploader = YouTubeAutoUploader(collections_root=str(tmp_path))

        with patch(
            "youtube_automation.agents._preflight.load_config",
            return_value=_make_preflight_config(["ja", "en"]),
        ):
            uploader._preflight_check(col_dir)

    def test_should_pass_when_required_high_cpm_languages_are_present(self, tmp_path):
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        col_dir = _write_preflight_collection(tmp_path, ["en", "ja", "de"])
        uploader = YouTubeAutoUploader(collections_root=str(tmp_path))

        with patch(
            "youtube_automation.agents._preflight.load_config",
            return_value=_make_preflight_config(["ja", "en", "de"]),
        ):
            uploader._preflight_check(col_dir)

    def test_should_warn_and_continue_when_low_cpm_language_is_present(self, tmp_path, caplog):
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        col_dir = _write_preflight_collection(tmp_path, ["en", "ja", "de", "ko"])
        uploader = YouTubeAutoUploader(collections_root=str(tmp_path))

        with (
            patch(
                "youtube_automation.agents._preflight.load_config",
                return_value=_make_preflight_config(["ja", "en", "de", "ko"]),
            ),
            caplog.at_level(logging.WARNING),
        ):
            uploader._preflight_check(col_dir)

        assert any("ko" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Issue #602: `_preflight_check` タイトル鋳型準拠ゲート
# ---------------------------------------------------------------------------


def _make_title_template_config(supported_languages: list[str]) -> SimpleNamespace:
    cfg = _make_preflight_config(supported_languages)
    # ` | ` 鋳型 + 核語彙を持つチャンネル（soulful-grooves 想定）に差し替え
    cfg.content.title = SimpleNamespace(
        template="{adjective} Soul/Funk {noun} | {hours} Hours of {mood}",
        template_check={"core_vocabulary": ["Soul", "Funk"]},
    )
    return cfg


def _write_title_collection(tmp_path: Path, title: str, *, status: str = "ready") -> Path:
    col_dir = tmp_path / status / "20990101-foo-collection"
    doc_dir = col_dir / "20-documentation"
    doc_dir.mkdir(parents=True)
    (doc_dir / "descriptions.md").write_text(
        "\n".join(
            [
                "## タイトル案",
                "```",
                title,
                "```",
                "",
                "## Complete Collection 概要欄",
                "```",
                "00:00 Opening Groove",
                "10:00 Midnight Funk",
                "20:00 Last Call Soul",
                "```",
                "",
                "## タグ（YouTube タグ欄）",
                "```",
                "soul funk, retro groove, study music",
                "```",
            ]
        ),
        encoding="utf-8",
    )
    scene_phrases = {lang: {"title": f"title-{lang}"} for lang in ["en", "ja", "de"]}
    (col_dir / "workflow-state.json").write_text(
        json.dumps({"scene_phrases": scene_phrases}),
        encoding="utf-8",
    )
    return col_dir


def _write_live_title(tmp_path: Path, slug: str, title: str) -> None:
    doc_dir = tmp_path / "live" / slug / "20-documentation"
    doc_dir.mkdir(parents=True)
    (doc_dir / "descriptions.md").write_text(
        f"## タイトル案\n```\n{title}\n```\n",
        encoding="utf-8",
    )


class TestPreflightTitleTemplateCompliance:
    """#602: 鋳型逸脱・巻数表記・RHS 重複を preflight で block する."""

    def test_should_fail_on_volume_and_rhs_duplicate(self, tmp_path):
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        _write_live_title(
            tmp_path,
            "20250101-vol1",
            "Pure Soul & Funk Infinity | 3 Hours of Soulful Retro Funk Grooves",
        )
        col_dir = _write_title_collection(
            tmp_path,
            "Funky Spirit Vol.2 | 3 Hours of Soulful Retro Funk Grooves",
        )
        uploader = YouTubeAutoUploader(collections_root=str(tmp_path))

        with patch(
            "youtube_automation.agents._preflight.load_config",
            return_value=_make_title_template_config(["ja", "en", "de"]),
        ):
            with pytest.raises(RuntimeError, match="タイトル鋳型違反"):
                uploader._preflight_check(col_dir)

    def test_should_pass_on_compliant_title(self, tmp_path):
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        _write_live_title(
            tmp_path,
            "20250101-vol1",
            "Pure Soul & Funk Infinity | 3 Hours of Soulful Retro Funk Grooves",
        )
        col_dir = _write_title_collection(
            tmp_path,
            "Bright Funk & Soul Spirit | 3 Hours of Feel-Good Retro Grooves",
        )
        uploader = YouTubeAutoUploader(collections_root=str(tmp_path))

        with patch(
            "youtube_automation.agents._preflight.load_config",
            return_value=_make_title_template_config(["ja", "en", "de"]),
        ):
            uploader._preflight_check(col_dir)


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

    def test_should_declare_contains_synthetic_media_true(self, tmp_path):
        """#603: AI 生成音楽を主軸とするため status.containsSyntheticMedia を true で申告する."""
        # Given
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        uploader = YouTubeAutoUploader(collections_root=str(tmp_path / "collections"))
        video = tmp_path / "v.mp4"
        video.write_bytes(b"\x00")

        with patch(
            "youtube_automation.agents.youtube_auto_uploader.YouTubeUploadCore.upload_video",
            return_value="VID_SYNTHETIC",
        ) as mock_core_upload:
            # When
            uploader.upload_video(str(video), _make_metadata())

        # Then: super().upload_video(video_path, body, ...) の body[status] を検証
        body = mock_core_upload.call_args.args[1]
        assert body["status"]["containsSyntheticMedia"] is True

    def test_should_default_self_declared_made_for_kids_false(self, tmp_path):
        """#605: config 未設定時は selfDeclaredMadeForKids=False の現行挙動を維持する."""
        # Given
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        uploader = YouTubeAutoUploader(collections_root=str(tmp_path / "collections"))
        video = tmp_path / "v.mp4"
        video.write_bytes(b"\x00")

        with patch(
            "youtube_automation.agents.youtube_auto_uploader.YouTubeUploadCore.upload_video",
            return_value="VID_KIDS",
        ) as mock_core_upload:
            # When
            uploader.upload_video(str(video), _make_metadata())

        # Then
        body = mock_core_upload.call_args.args[1]
        assert body["status"]["selfDeclaredMadeForKids"] is False

    def test_should_resolve_synthetic_media_flags_from_config(self, tmp_path):
        """#605: status フラグを config（youtube.api）から解決する."""
        # Given
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        uploader = YouTubeAutoUploader(collections_root=str(tmp_path / "collections"))
        video = tmp_path / "v.mp4"
        video.write_bytes(b"\x00")

        fake_config = SimpleNamespace(
            youtube=SimpleNamespace(
                api=SimpleNamespace(
                    contains_synthetic_media=False,
                    self_declared_made_for_kids=True,
                )
            )
        )

        with (
            patch(
                "youtube_automation.agents.youtube_auto_uploader.load_config",
                return_value=fake_config,
            ),
            patch(
                "youtube_automation.agents.youtube_auto_uploader.YouTubeUploadCore.upload_video",
                return_value="VID_CONFIG",
            ) as mock_core_upload,
        ):
            # When
            uploader.upload_video(str(video), _make_metadata())

        # Then: config の値が status へ反映される
        body = mock_core_upload.call_args.args[1]
        assert body["status"]["containsSyntheticMedia"] is False
        assert body["status"]["selfDeclaredMadeForKids"] is True

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
        mock_youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": "v9", "snippet": {"title": "Rainy Jazz"}, "status": {"uploadStatus": "processed"}},
            ]
        }

        # When
        result = uploader._find_existing_video_by_title("Rainy Jazz")

        # Then
        assert result == {
            "video_id": "v9",
            "video_url": "https://www.youtube.com/watch?v=v9",
        }

    def test_should_revalidate_exact_search_match_with_videos_list(self, tmp_path):
        """search の完全一致候補は videos.list で再検証してから採用する."""
        # Given
        uploader, mock_youtube = self._make_uploader_with_mock_youtube(tmp_path)
        mock_youtube.search.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": {"videoId": "v9"}, "snippet": {"title": "Rainy Jazz"}},
            ]
        }
        mock_youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": "v9", "snippet": {"title": "Rainy Jazz"}, "status": {"uploadStatus": "processed"}},
            ]
        }

        # When
        uploader._find_existing_video_by_title("Rainy Jazz")

        # Then
        mock_youtube.videos.return_value.list.assert_called_once_with(id="v9", part="status,snippet")

    def test_should_return_none_when_search_hit_no_longer_exists_in_videos_list(self, tmp_path):
        """削除済み動画が search index に残っていても dedup hit にしない."""
        # Given
        uploader, mock_youtube = self._make_uploader_with_mock_youtube(tmp_path)
        mock_youtube.search.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": {"videoId": "stale"}, "snippet": {"title": "Rainy Jazz"}},
            ]
        }
        mock_youtube.videos.return_value.list.return_value.execute.return_value = {"items": []}

        # When
        result = uploader._find_existing_video_by_title("Rainy Jazz")

        # Then
        assert result is None

    def test_should_return_none_when_videos_list_title_differs_from_search_hit(self, tmp_path):
        """videos.list 側のタイトルが一致しない候補は採用しない."""
        # Given
        uploader, mock_youtube = self._make_uploader_with_mock_youtube(tmp_path)
        mock_youtube.search.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": {"videoId": "v9"}, "snippet": {"title": "Rainy Jazz"}},
            ]
        }
        mock_youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": "v9", "snippet": {"title": "Rainy Jazz Remastered"}, "status": {"uploadStatus": "processed"}},
            ]
        }

        # When
        result = uploader._find_existing_video_by_title("Rainy Jazz")

        # Then
        assert result is None

    def test_should_return_none_when_videos_list_upload_status_is_not_reusable(self, tmp_path):
        """videos.list 側の uploadStatus が failed の候補は採用しない."""
        # Given
        uploader, mock_youtube = self._make_uploader_with_mock_youtube(tmp_path)
        mock_youtube.search.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": {"videoId": "v9"}, "snippet": {"title": "Rainy Jazz"}},
            ]
        }
        mock_youtube.videos.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": "v9", "snippet": {"title": "Rainy Jazz"}, "status": {"uploadStatus": "failed"}},
            ]
        }

        # When
        result = uploader._find_existing_video_by_title("Rainy Jazz")

        # Then
        assert result is None

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
        assert result["upload_source"] == "existing_video"

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
        assert result["upload_source"] == "new_upload"

    def test_should_proceed_with_upload_when_search_api_raises_http_error(self, tmp_path, caplog):
        """plan 要件 #10: search API 自体が HttpError を投げたケースで fail-open で upload 続行."""
        # Given
        uploader, col_dir, mock_gen = self._setup(tmp_path)

        # 実 youtube.search を HttpError で失敗させ、`_find_existing_video_by_title`
        # の fail-open 経路（HttpError → warning + None 返却）を実コードで通す
        mock_youtube = MagicMock()
        mock_youtube.search.return_value.list.return_value.execute.side_effect = _make_http_error(500)
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


# ---------------------------------------------------------------------------
# Issue #1053: active channel visibility
# ---------------------------------------------------------------------------


class TestActiveChannelVisibility:
    """誤投稿防止のため操作中チャンネルをログ表示する."""

    def test_should_log_active_channel_identity(self, tmp_path, caplog):
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        uploader = YouTubeAutoUploader(collections_root=str(tmp_path))
        cfg = SimpleNamespace(
            meta=SimpleNamespace(
                channel_name="Rainy Jazz Night",
                youtube_handle="@rainyjazz",
                channel_id="UC123",
            )
        )

        with (
            patch("youtube_automation.agents.youtube_auto_uploader.load_config", return_value=cfg),
            caplog.at_level(logging.INFO),
        ):
            uploader._log_active_channel()

        messages = "\n".join(record.getMessage() for record in caplog.records)
        assert "操作中チャンネル" in messages
        assert "Rainy Jazz Night" in messages
        assert "@rainyjazz" in messages
        assert "UC123" in messages


# ---------------------------------------------------------------------------
# Issue #647: scheduled publish (status.publishAt) regression
# ---------------------------------------------------------------------------


class TestUploadVideoScheduledPublish:
    """`upload_video` が publish_at を渡された時に正しく status.publishAt を構築する.

    バグレポート（#647）: 予約投稿の設定をしても即時公開された FB の再発防止。
    """

    def test_should_set_publish_at_and_force_private_when_publish_at_provided(self, tmp_path):
        """publish_at 指定時は status.publishAt と privacyStatus=private を必ず設定する."""
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        uploader = YouTubeAutoUploader(collections_root=str(tmp_path / "collections"))
        video = tmp_path / "v.mp4"
        video.write_bytes(b"\x00")

        metadata = _make_metadata()
        metadata["privacy_status"] = "public"  # ユーザーが間違って public を入れていても
        metadata["publish_at"] = "2099-01-01T20:00:00+09:00"

        with patch(
            "youtube_automation.agents.youtube_auto_uploader.YouTubeUploadCore.upload_video",
            return_value="VID_SCHEDULED",
        ) as mock_core_upload:
            uploader.upload_video(str(video), metadata)

        body = mock_core_upload.call_args.args[1]
        # publishAt は API 仕様上 privacyStatus=private が必須
        assert body["status"]["privacyStatus"] == "private"
        # publishAt は UTC（Z 終端）に正規化される
        assert body["status"]["publishAt"] == "2099-01-01T11:00:00Z"

    def test_should_normalize_publish_at_to_utc(self, tmp_path):
        """+09:00 のような timezone offset 付き値は UTC (Z) に正規化される."""
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        uploader = YouTubeAutoUploader(collections_root=str(tmp_path / "collections"))
        video = tmp_path / "v.mp4"
        video.write_bytes(b"\x00")

        metadata = _make_metadata()
        metadata["publish_at"] = "2099-06-15T20:00:00+09:00"

        with patch(
            "youtube_automation.agents.youtube_auto_uploader.YouTubeUploadCore.upload_video",
            return_value="VID_NORMALIZED",
        ) as mock_core_upload:
            uploader.upload_video(str(video), metadata)

        body = mock_core_upload.call_args.args[1]
        assert body["status"]["publishAt"] == "2099-06-15T11:00:00Z"

    def test_should_passthrough_already_utc_publish_at(self, tmp_path):
        """既に UTC (Z) の publish_at はそのまま透過する."""
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        uploader = YouTubeAutoUploader(collections_root=str(tmp_path / "collections"))
        video = tmp_path / "v.mp4"
        video.write_bytes(b"\x00")

        metadata = _make_metadata()
        metadata["publish_at"] = "2099-06-15T11:00:00Z"

        with patch(
            "youtube_automation.agents.youtube_auto_uploader.YouTubeUploadCore.upload_video",
            return_value="VID_UTC",
        ) as mock_core_upload:
            uploader.upload_video(str(video), metadata)

        body = mock_core_upload.call_args.args[1]
        assert body["status"]["publishAt"] == "2099-06-15T11:00:00Z"

    def test_should_omit_publish_at_when_metadata_does_not_have_it(self, tmp_path):
        """publish_at が無いメタデータでは status.publishAt は付与されない（即時公開経路）."""
        from youtube_automation.agents.youtube_auto_uploader import YouTubeAutoUploader

        uploader = YouTubeAutoUploader(collections_root=str(tmp_path / "collections"))
        video = tmp_path / "v.mp4"
        video.write_bytes(b"\x00")

        with patch(
            "youtube_automation.agents.youtube_auto_uploader.YouTubeUploadCore.upload_video",
            return_value="VID_IMMEDIATE",
        ) as mock_core_upload:
            uploader.upload_video(str(video), _make_metadata())

        body = mock_core_upload.call_args.args[1]
        assert "publishAt" not in body["status"]


class TestNormalizePublishAt:
    """`_normalize_publish_at` の単体テスト."""

    def test_jst_offset_is_converted_to_utc_z(self):
        from youtube_automation.agents.youtube_auto_uploader import _normalize_publish_at

        assert _normalize_publish_at("2099-06-15T20:00:00+09:00") == "2099-06-15T11:00:00Z"

    def test_utc_z_passthrough(self):
        from youtube_automation.agents.youtube_auto_uploader import _normalize_publish_at

        assert _normalize_publish_at("2099-06-15T11:00:00Z") == "2099-06-15T11:00:00Z"

    def test_invalid_string_returns_as_is(self):
        from youtube_automation.agents.youtube_auto_uploader import _normalize_publish_at

        # パース不能ならそのまま返す（呼び出し側に責務を任せる）
        assert _normalize_publish_at("not-an-iso-date") == "not-an-iso-date"

    def test_naive_iso_returns_as_is(self):
        from youtube_automation.agents.youtube_auto_uploader import _normalize_publish_at

        # naive datetime は TZ 不明 → そのまま返す
        assert _normalize_publish_at("2099-06-15T11:00:00") == "2099-06-15T11:00:00"
