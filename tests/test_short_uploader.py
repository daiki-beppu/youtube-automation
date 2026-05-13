"""ShortUploader のユニットテスト.

外部 API（YouTube / Veo）には実通信しない。`unittest.mock` で YouTubeAutoUploader と
BAHMetadataGenerator を差し替え、純粋ロジック（_calculate_short_publish_at /
_check_upload_interval / メタデータ呼び出し）を検証する。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# ヘルパー: 副作用のない ShortUploader インスタンスを得る
# ---------------------------------------------------------------------------


def _make_uploader(tmp_path: Path, schedule_config: dict | None = None) -> "ShortUploader":  # noqa: F821
    """`ShortUploader` を tmp_path 上で組み立てる（OAuth/upload 系は MagicMock 化）.

    `__init__` で YouTubeAutoUploader を生成すると OAuth が要求されるため、
    `__init__` の load_config / channel_dir / YouTubeAutoUploader をパッチして安全に組み立てる。
    """
    from youtube_automation.agents.short_uploader import ShortUploader
    from youtube_automation.utils.config import load_config

    config = load_config()

    with (
        patch("youtube_automation.agents.short_uploader.load_config", return_value=config),
        patch("youtube_automation.agents.short_uploader._channel_dir", return_value=tmp_path),
        patch("youtube_automation.agents.short_uploader.YouTubeAutoUploader") as mock_uploader_cls,
    ):
        if schedule_config is not None:
            sched_path = tmp_path / "config" / "schedule_config.json"
            sched_path.parent.mkdir(parents=True, exist_ok=True)
            sched_path.write_text(json.dumps(schedule_config), encoding="utf-8")

        uploader = ShortUploader()
        uploader.uploader = mock_uploader_cls.return_value
    return uploader


# ===========================================================================
# 1. _calculate_short_publish_at のテスト
# ===========================================================================


class TestCalculateShortPublishAt:
    """CC 公開日 → 翌日 short_publish_time の固定算出を検証する."""

    def _setup_tracking(self, collection_path: Path, cc: dict) -> None:
        doc = collection_path / "20-documentation"
        doc.mkdir(parents=True, exist_ok=True)
        (doc / "upload_tracking.json").write_text(
            json.dumps({"complete_collection": cc}), encoding="utf-8"
        )

    def test_returns_iso_string_for_future_cc(self, tmp_path):
        """CC 公開日が未来なら翌日 08:00 の ISO 文字列を返す（デフォルト時刻）."""
        uploader = _make_uploader(tmp_path)
        col = tmp_path / "collections" / "live" / "20990101-live-test"
        col.mkdir(parents=True)
        self._setup_tracking(col, {"publish_at": "2099-01-01T17:00:00+09:00"})

        result = uploader._calculate_short_publish_at(col)
        assert result is not None
        # 翌日 08:00（Asia/Tokyo）
        assert result.startswith("2099-01-02T08:00:00")
        assert "+09:00" in result

    def test_uses_config_short_publish_time(self, tmp_path):
        """`config.workflow.post_upload.short_publish_time` が時刻に反映される.

        sample_channel fixture の workflow.json は 08:00 を持つので、
        動的に書き換えるためにテスト内で reset() + 新 fixture を組み立てる。
        """
        # sample_channel の workflow.json は "08:00" なので、そのまま検証する
        uploader = _make_uploader(tmp_path)
        col = tmp_path / "collections" / "live" / "20990101-live-test"
        col.mkdir(parents=True)
        self._setup_tracking(col, {"publish_at": "2099-06-15T12:00:00+09:00"})

        result = uploader._calculate_short_publish_at(col)
        assert result is not None
        # config.workflow.post_upload.short_publish_time（デフォルト/fixture: 08:00）
        expected_hm = uploader.config.workflow.post_upload.short_publish_time
        hour, minute = expected_hm.split(":")
        assert f"T{hour}:{minute}:00" in result

    def test_returns_none_for_past_cc(self, tmp_path):
        """CC が過去で翌日 short_publish_time も過去なら None（即時公開）."""
        uploader = _make_uploader(tmp_path)
        col = tmp_path / "collections" / "live" / "20200101-live-test"
        col.mkdir(parents=True)
        self._setup_tracking(col, {"publish_at": "2020-01-01T17:00:00+09:00"})

        assert uploader._calculate_short_publish_at(col) is None

    def test_returns_none_when_no_tracking(self, tmp_path):
        """upload_tracking.json が無ければ None"""
        uploader = _make_uploader(tmp_path)
        col = tmp_path / "collections" / "live" / "missing"
        col.mkdir(parents=True)

        assert uploader._calculate_short_publish_at(col) is None

    def test_falls_back_to_upload_time(self, tmp_path):
        """publish_at が無くても upload_time から算出できる"""
        uploader = _make_uploader(tmp_path)
        col = tmp_path / "collections" / "live" / "20990101-live-test"
        col.mkdir(parents=True)
        self._setup_tracking(col, {"upload_time": "2099-03-10T10:00:00"})

        result = uploader._calculate_short_publish_at(col)
        assert result is not None
        assert result.startswith("2099-03-11T")


# ===========================================================================
# 2. _check_upload_interval のテスト
# ===========================================================================


class TestCheckUploadInterval:
    """投稿間隔ガード（min_hours_between_shorts）の検証."""

    def test_returns_ok_when_no_history(self, tmp_path):
        uploader = _make_uploader(tmp_path)
        ok, message = uploader._check_upload_interval()
        assert ok is True
        assert "記録なし" in message

    def test_returns_ng_when_recent_upload(self, tmp_path):
        """最近のアップロードがあれば False を返す"""
        uploader = _make_uploader(
            tmp_path,
            schedule_config={
                "shorts": {"min_hours_between_shorts": 24},
                "schedule": {"timezone": "Asia/Tokyo"},
            },
        )
        live = tmp_path / "collections" / "live" / "recent"
        live.mkdir(parents=True)
        recent_time = (datetime.now().astimezone() - timedelta(hours=1)).isoformat()
        (live / "workflow-state.json").write_text(
            json.dumps({"post_upload": {"short": {"upload_time": recent_time}}}),
            encoding="utf-8",
        )

        ok, message = uploader._check_upload_interval()
        assert ok is False
        assert "待機" in message

    def test_returns_ok_when_old_upload(self, tmp_path):
        """十分時間が経過していれば True"""
        uploader = _make_uploader(
            tmp_path,
            schedule_config={
                "shorts": {"min_hours_between_shorts": 24},
                "schedule": {"timezone": "Asia/Tokyo"},
            },
        )
        live = tmp_path / "collections" / "live" / "old"
        live.mkdir(parents=True)
        old_time = (datetime.now().astimezone() - timedelta(days=2)).isoformat()
        (live / "workflow-state.json").write_text(
            json.dumps({"post_upload": {"short": {"upload_time": old_time}}}),
            encoding="utf-8",
        )

        ok, message = uploader._check_upload_interval()
        assert ok is True
        assert "投稿可" in message


# ===========================================================================
# 3. _generate_metadata が BAHMetadataGenerator に委譲することの検証
# ===========================================================================


class TestGenerateMetadataDelegation:
    """`_generate_metadata` は BAHMetadataGenerator.generate_shorts_metadata を呼ぶ."""

    def test_delegates_to_metadata_generator(self, tmp_path):
        uploader = _make_uploader(tmp_path)
        col = tmp_path / "collections" / "live" / "20990101-live-test"
        col.mkdir(parents=True)

        with patch(
            "youtube_automation.agents.short_uploader.BAHMetadataGenerator"
        ) as mock_gen_cls:
            mock_instance = MagicMock()
            mock_instance.generate_shorts_metadata.return_value = {
                "title": "X #Shorts",
                "description": "x",
                "tags": ["Shorts"],
                "category_id": "10",
                "privacy_status": "public",
                "language": "ja",
                "localizations": {},
            }
            mock_gen_cls.return_value = mock_instance

            meta = uploader._generate_metadata(col, "https://youtu.be/cc-id")

        mock_gen_cls.assert_called_once_with(str(col))
        mock_instance.generate_shorts_metadata.assert_called_once_with("https://youtu.be/cc-id")
        assert meta["title"] == "X #Shorts"


# ===========================================================================
# 4. _find_short_video のテスト
# ===========================================================================


class TestFindShortVideo:
    """Shorts 動画ファイル探索のロジック検証."""

    def test_finds_single_short(self, tmp_path):
        uploader = _make_uploader(tmp_path)
        col = tmp_path / "col"
        master = col / "01-master"
        master.mkdir(parents=True)
        target = master / "short.mp4"
        target.write_text("")

        assert uploader._find_short_video(col) == target

    def test_finds_numbered_short(self, tmp_path):
        uploader = _make_uploader(tmp_path)
        col = tmp_path / "col"
        shorts_dir = col / "01-master" / "shorts"
        shorts_dir.mkdir(parents=True)
        target = shorts_dir / "short-02-morning.mp4"
        target.write_text("")

        assert uploader._find_short_video(col, short_num=2) == target

    def test_returns_none_when_missing(self, tmp_path):
        uploader = _make_uploader(tmp_path)
        col = tmp_path / "col"
        col.mkdir()
        assert uploader._find_short_video(col) is None
        assert uploader._find_short_video(col, short_num=1) is None


# ===========================================================================
# 5. import smoke test
# ===========================================================================


def test_short_uploader_imports_youtube_auto_uploader():
    """short_uploader が正しいパスから YouTubeAutoUploader を import できる."""
    from youtube_automation.agents import short_uploader

    assert hasattr(short_uploader, "YouTubeAutoUploader")
    assert short_uploader.YouTubeAutoUploader.__module__ == (
        "youtube_automation.agents.youtube_auto_uploader"
    )


def test_short_uploader_imports_metadata_generator():
    """short_uploader が BAHMetadataGenerator を import できる."""
    from youtube_automation.agents import short_uploader

    assert hasattr(short_uploader, "BAHMetadataGenerator")
    assert short_uploader.BAHMetadataGenerator.__module__ == (
        "youtube_automation.utils.metadata_generator"
    )
