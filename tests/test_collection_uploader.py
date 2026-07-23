"""
CollectionUploader のユニットテスト

テスト対象: agents/collection_uploader.py

#77 回帰テスト: `_assign_to_playlists()` の import パス誤りで
プレイリスト自動追加が常時失敗していたバグを検出するためのテスト。
"""

import json
import logging
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# import smoke test (#77)
# ---------------------------------------------------------------------------


def test_collection_uploader_imports_playlist_manager():
    """collection_uploader は PlaylistManager を正しいパスから import できる。

    #77 の回帰防止: 誤った `from playlist_manager import PlaylistManager` が
    残っているとモジュールロード時点で ImportError になる。
    """
    from youtube_automation.agents import collection_uploader

    assert hasattr(collection_uploader, "PlaylistManager")
    assert collection_uploader.PlaylistManager.__module__ == "youtube_automation.scripts.playlist_manager"


@pytest.mark.parametrize(
    ("argv", "method_name"),
    [(["--plan"], "show_plan"), ([], "execute_next_step")],
)
def test_main_runs_shared_preflight_before_plan_or_execute(monkeypatch, tmp_path, argv, method_name):
    """実行可能な CLI 入口は upload preflight を通してから処理する。"""
    from youtube_automation.agents import collection_uploader

    target = tmp_path / "collections" / "planning" / "20990101-test-collection"
    target.mkdir(parents=True)
    mock_config = MagicMock()
    mock_config.meta.channel_short = "test"
    mock_uploader = MagicMock()
    mock_uploader._find_collection.return_value = target

    monkeypatch.setattr(sys, "argv", ["yt-upload-collection", *argv])
    with (
        patch("youtube_automation.agents.collection_uploader.load_config", return_value=mock_config),
        patch("youtube_automation.agents.collection_uploader.CollectionUploader", return_value=mock_uploader),
    ):
        collection_uploader.main()

    mock_uploader.ensure_upload_preflight.assert_called_once_with(target)
    getattr(mock_uploader, method_name).assert_called_once_with(target)


def _write_cli_title_collection(channel_dir: Path, *, title_template_check: dict[str, object] | None) -> Path:
    """CLI が実際に解決する planning コレクションを作る。"""
    collection = channel_dir / "collections" / "planning" / "20990101-volume-collection"
    for subdir in ("01-master", "02-Individual-music", "03-Individual-movie", "10-assets", "20-documentation"):
        (collection / subdir).mkdir(parents=True, exist_ok=True)
    (collection / "20-documentation" / "descriptions.md").write_text(
        """## タイトル案
```
Funky Soul Spirit Vol.2 | 3 Hours of Feel-Good Retro Grooves
```

## Complete Collection 概要欄
```
00:00 Opening Groove
10:00 Midnight Funk
20:00 Last Call Soul
```

## タグ（YouTube タグ欄）
```
soul funk, retro groove, study music
```
""",
        encoding="utf-8",
    )
    state: dict[str, object] = {"scene_phrases": {lang: {"title": f"title-{lang}"} for lang in ("ja", "en", "de")}}
    if title_template_check is not None:
        state["title_template_check"] = title_template_check
    (collection / "workflow-state.json").write_text(json.dumps(state), encoding="utf-8")
    return collection


def _title_preflight_config() -> SimpleNamespace:
    return SimpleNamespace(
        audio=SimpleNamespace(chapter_max=100),
        content=SimpleNamespace(
            tags=SimpleNamespace(min_count=None, for_collection=lambda _name: ["fallback"]),
            title=SimpleNamespace(
                template="{adjective} Soul/Funk {noun} | {hours} Hours of {mood}",
                template_check={"core_vocabulary": ["Soul", "Funk"]},
            ),
        ),
        localizations=SimpleNamespace(supported_languages=["ja", "en", "de"]),
    )


@pytest.mark.parametrize(
    ("argv", "method_name"),
    [(["--plan"], "show_plan"), ([], "execute_next_step")],
)
@pytest.mark.parametrize(
    ("title_template_check", "expected_outcome"),
    [({"allow_volume_patterns": True}, "pass"), (None, "fail")],
)
def test_main_title_preflight_honors_collection_opt_in_for_each_cli_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    method_name: str,
    title_template_check: dict[str, object] | None,
    expected_outcome: str,
) -> None:
    """実行可能な CLI 入口が state の title opt-in を実際に評価する。"""
    from youtube_automation.agents import collection_uploader
    from youtube_automation.agents.collection_uploader import CollectionUploader
    from youtube_automation.configuration import reset as reset_config

    fixture_channel = Path(__file__).parent / "fixtures" / "sample_channel"
    test_channel = tmp_path / "channel"
    shutil.copytree(fixture_channel, test_channel)
    collection = _write_cli_title_collection(test_channel, title_template_check=title_template_check)
    mock_config = MagicMock()
    mock_config.meta.channel_short = "test"

    monkeypatch.setenv("CHANNEL_DIR", str(test_channel))
    monkeypatch.setattr(sys, "argv", ["yt-upload-collection", *argv, "-c", collection.name])
    reset_config()

    with (
        patch("youtube_automation.agents.collection_uploader.load_config", return_value=mock_config),
        patch("youtube_automation.agents._preflight.load_config", return_value=_title_preflight_config()),
        patch.object(CollectionUploader, method_name) as mock_action,
    ):
        if expected_outcome == "pass":
            collection_uploader.main()
            mock_action.assert_called_once_with(collection)
        else:
            with pytest.raises(SystemExit, match="1"):
                collection_uploader.main()
            assert "巻数表記を検出" in capsys.readouterr().out
            mock_action.assert_not_called()


# ---------------------------------------------------------------------------
# _assign_to_playlists
# ---------------------------------------------------------------------------


@pytest.fixture
def workflow_state_file(tmp_path):
    """workflow-state.json を含むコレクションディレクトリを返す"""
    ws_path = tmp_path / "workflow-state.json"
    ws_path.write_text(json.dumps({"theme": "Rainy Jazz"}), encoding="utf-8")
    return tmp_path


def test_assign_to_playlists_calls_playlist_manager(workflow_state_file):
    """`_assign_to_playlists` が PlaylistManager.assign_video を theme 付きで呼ぶ。

    #77 の回帰防止: import パスが正しくなければ以前は ImportError が warning に
    握り潰されて何も呼ばれなかった。
    """
    from youtube_automation.agents.collection_uploader import CollectionUploader

    mock_config = MagicMock()
    mock_config.playlists.items = {"all": {"title": "All", "playlist_id": "PL_ALL"}}

    mock_pm_instance = MagicMock()
    mock_pm_instance.assign_video.return_value = ["all"]

    with (
        patch("youtube_automation.agents.collection_uploader.load_config", return_value=mock_config),
        patch(
            "youtube_automation.agents.collection_uploader.PlaylistManager",
            return_value=mock_pm_instance,
        ) as mock_pm_class,
    ):
        # self を使わないメソッドなので MagicMock インスタンスで十分
        fake_self = MagicMock()
        CollectionUploader._assign_to_playlists(fake_self, "VIDEO_ID_123", workflow_state_file)

    mock_pm_class.assert_called_once_with()
    mock_pm_instance.assign_video.assert_called_once_with(
        "VIDEO_ID_123", "Rainy Jazz", collection_path=workflow_state_file
    )


def test_assign_to_playlists_skips_when_no_theme(tmp_path):
    """theme が空なら PlaylistManager を呼ばずに return する"""
    from youtube_automation.agents.collection_uploader import CollectionUploader

    ws_path = tmp_path / "workflow-state.json"
    ws_path.write_text(json.dumps({"theme": ""}), encoding="utf-8")

    with (
        patch("youtube_automation.agents.collection_uploader.load_config") as mock_load,
        patch("youtube_automation.agents.collection_uploader.PlaylistManager") as mock_pm_class,
    ):
        fake_self = MagicMock()
        CollectionUploader._assign_to_playlists(fake_self, "VIDEO_ID_123", tmp_path)

    mock_load.assert_not_called()
    mock_pm_class.assert_not_called()


def test_assign_to_playlists_skips_when_no_workflow_state(tmp_path):
    """workflow-state.json がなければ何もしない"""
    from youtube_automation.agents.collection_uploader import CollectionUploader

    with (
        patch("youtube_automation.agents.collection_uploader.load_config") as mock_load,
        patch("youtube_automation.agents.collection_uploader.PlaylistManager") as mock_pm_class,
    ):
        fake_self = MagicMock()
        CollectionUploader._assign_to_playlists(fake_self, "VIDEO_ID_123", tmp_path)

    mock_load.assert_not_called()
    mock_pm_class.assert_not_called()


# ---------------------------------------------------------------------------
# _execute_complete_collection: resumable upload session URI 連携 (issue #381)
# ---------------------------------------------------------------------------


_SESS_PREV = "https://upload.googleapis.com/SESS_PREV"
_SESS_NEW = "https://upload.googleapis.com/SESS_NEW"


def _make_tracking_collection(
    tmp_path: Path,
    *,
    resume_uri: str | None = None,
    cc_status: str = "pending",
    extra_cc: dict | None = None,
) -> tuple[Path, Path]:
    """tracking JSON 入りコレクションディレクトリを作って (collection_path, tracking_path) を返す."""
    col = tmp_path / "collections" / "planning" / "20990101-foo-collection"
    col.mkdir(parents=True)
    (col / "01-master").mkdir()
    doc = col / "20-documentation"
    doc.mkdir()
    (col / "workflow-state.json").write_text(
        json.dumps(
            {
                "collection_name": col.name,
                "theme": "",
                "stage": "planning",
                "phase": "publishing",
                "upload": {"video_id": None, "video_url": None, "publish_at": None},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    cc: dict = {"status": cc_status}
    if resume_uri is not None:
        cc["resume_session_uri"] = resume_uri
    if extra_cc:
        cc.update(extra_cc)

    tracking = {
        "schema_version": 3,
        "collection_name": col.name,
        "status": "in_progress",
        "complete_collection": cc,
    }
    tracking_path = doc / "upload_tracking.json"
    tracking_path.write_text(json.dumps(tracking, ensure_ascii=False, indent=2), encoding="utf-8")
    return col, tracking_path


def _make_uploader_with_collection_mock(tmp_path: Path):
    """CollectionUploader を構築し、内部の self.uploader を MagicMock に差し替える."""
    from youtube_automation.agents.collection_uploader import CollectionUploader

    with patch("youtube_automation.agents.collection_uploader.YouTubeAutoUploader") as mock_cls:
        mock_inner = MagicMock()
        mock_cls.return_value = mock_inner
        uploader = CollectionUploader(collections_root=str(tmp_path / "collections"))
        # auto_move_to_live を無効化してパス変動を防ぐ
        uploader.config["collections_management"]["auto_move_to_live"] = False
        return uploader, mock_inner


def _make_uploader_with_schedule_config(tmp_path: Path, schedule_config: dict):
    """schedule_config.json を指定して CollectionUploader を構築する."""
    from youtube_automation.agents.collection_uploader import CollectionUploader

    config_path = tmp_path / "schedule_config.json"
    config_path.write_text(json.dumps(schedule_config), encoding="utf-8")

    with patch("youtube_automation.agents.collection_uploader.YouTubeAutoUploader") as mock_cls:
        mock_inner = MagicMock()
        mock_cls.return_value = mock_inner
        uploader = CollectionUploader(
            collections_root=str(tmp_path / "collections"),
            config_path=str(config_path),
        )
        uploader.config["collections_management"]["auto_move_to_live"] = False
        return uploader, mock_inner


def _read_resume_uri(tracking_path: Path) -> str | None:
    data = json.loads(tracking_path.read_text(encoding="utf-8"))
    return data.get("complete_collection", {}).get("resume_session_uri")


def _write_workflow_state(collection: Path, *, phase: str, video_id: str | None) -> None:
    collection.mkdir(parents=True)
    (collection / "workflow-state.json").write_text(
        json.dumps({"phase": phase, "upload": {"video_id": video_id}}), encoding="utf-8"
    )


class TestAutoDetectCollection:
    def test_auto_detect_selects_only_unpublished_mastered_planning_collection(self, tmp_path):
        uploader, _ = _make_uploader_with_collection_mock(tmp_path)
        live = tmp_path / "collections" / "live" / "20260101-published-collection"
        target = tmp_path / "collections" / "planning" / "20260201-mastered-collection"
        _write_workflow_state(live, phase="complete", video_id="published-video")
        _write_workflow_state(target, phase="mastered", video_id=None)

        assert uploader._find_collection() == target

    def test_auto_detect_fails_when_no_unpublished_mastered_planning_collection(self, tmp_path):
        from youtube_automation.utils.exceptions import ValidationError

        uploader, _ = _make_uploader_with_collection_mock(tmp_path)
        _write_workflow_state(
            tmp_path / "collections" / "live" / "20260101-published-collection",
            phase="complete",
            video_id="published-video",
        )
        _write_workflow_state(
            tmp_path / "collections" / "planning" / "20260201-uploaded-collection",
            phase="mastered",
            video_id="already-uploaded",
        )

        with pytest.raises(ValidationError, match="自動選択できる対象コレクションがありません"):
            uploader._find_collection()

    def test_auto_detect_fails_when_video_id_is_missing(self, tmp_path):
        from youtube_automation.utils.exceptions import ValidationError

        uploader, _ = _make_uploader_with_collection_mock(tmp_path)
        collection = tmp_path / "collections" / "planning" / "20260201-incomplete-collection"
        collection.mkdir(parents=True)
        (collection / "workflow-state.json").write_text(
            json.dumps({"phase": "mastered", "upload": {}}), encoding="utf-8"
        )

        with pytest.raises(ValidationError, match="自動選択できる対象コレクションがありません"):
            uploader._find_collection()

    def test_auto_detect_fails_when_multiple_unpublished_mastered_planning_collections(self, tmp_path):
        from youtube_automation.utils.exceptions import ValidationError

        uploader, _ = _make_uploader_with_collection_mock(tmp_path)
        _write_workflow_state(
            tmp_path / "collections" / "planning" / "20260201-first-collection", phase="mastered", video_id=None
        )
        _write_workflow_state(
            tmp_path / "collections" / "planning" / "20260202-second-collection", phase="mastered", video_id=None
        )

        with pytest.raises(ValidationError, match="-c で対象を明示してください"):
            uploader._find_collection()

    def test_explicit_collection_name_can_still_select_live_collection(self, tmp_path):
        uploader, _ = _make_uploader_with_collection_mock(tmp_path)
        live = tmp_path / "collections" / "live" / "20260101-published-collection"
        _write_workflow_state(live, phase="complete", video_id="published-video")

        assert uploader._find_collection("published") == live

    @pytest.mark.parametrize(
        ("argv", "method_name"),
        [(["--status"], "show_status"), (["--plan"], "show_plan"), ([], "execute_next_step")],
    )
    def test_main_uses_safe_auto_detect_for_status_plan_and_upload(self, monkeypatch, tmp_path, argv, method_name):
        from youtube_automation.agents import collection_uploader

        uploader, _ = _make_uploader_with_collection_mock(tmp_path)
        live = tmp_path / "collections" / "live" / "20260101-published-collection"
        target = tmp_path / "collections" / "planning" / "20260201-mastered-collection"
        _write_workflow_state(live, phase="complete", video_id="published-video")
        _write_workflow_state(target, phase="mastered", video_id=None)
        method = MagicMock()
        monkeypatch.setattr(uploader, method_name, method)
        mock_config = MagicMock()
        mock_config.meta.channel_short = "test"

        monkeypatch.setattr(sys, "argv", ["yt-upload-collection", *argv])
        with (
            patch("youtube_automation.agents.collection_uploader.load_config", return_value=mock_config),
            patch("youtube_automation.agents.collection_uploader.CollectionUploader", return_value=uploader),
            patch("youtube_automation.agents.collection_uploader.ensure_collection_preflight") as mock_preflight,
        ):
            collection_uploader.main()

        method.assert_called_once_with(target)
        if argv == ["--status"]:
            mock_preflight.assert_not_called()
        else:
            mock_preflight.assert_called_once_with(target)

    @pytest.mark.parametrize("argv", [["--status"], ["--plan"], []])
    def test_main_fails_loudly_when_auto_detect_has_no_candidate(self, monkeypatch, tmp_path, capsys, argv):
        from youtube_automation.agents import collection_uploader

        uploader, _ = _make_uploader_with_collection_mock(tmp_path)
        mock_config = MagicMock()
        mock_config.meta.channel_short = "test"
        monkeypatch.setattr(sys, "argv", ["yt-upload-collection", *argv])

        with (
            patch("youtube_automation.agents.collection_uploader.load_config", return_value=mock_config),
            patch("youtube_automation.agents.collection_uploader.CollectionUploader", return_value=uploader),
            pytest.raises(SystemExit) as exc_info,
        ):
            collection_uploader.main()

        assert exc_info.value.code == 1
        assert "-c で対象を明示してください" in capsys.readouterr().out

    @pytest.mark.parametrize(
        ("argv", "method_name"),
        [(["--status"], "show_status"), (["--plan"], "show_plan"), ([], "execute_next_step")],
    )
    def test_main_fails_loudly_when_auto_detect_is_ambiguous(self, monkeypatch, tmp_path, capsys, argv, method_name):
        from youtube_automation.agents import collection_uploader

        uploader, _ = _make_uploader_with_collection_mock(tmp_path)
        _write_workflow_state(
            tmp_path / "collections" / "planning" / "20260201-first-collection", phase="mastered", video_id=None
        )
        _write_workflow_state(
            tmp_path / "collections" / "planning" / "20260202-second-collection", phase="mastered", video_id=None
        )
        mock_config = MagicMock()
        mock_config.meta.channel_short = "test"
        method = MagicMock()
        monkeypatch.setattr(uploader, method_name, method)
        monkeypatch.setattr(sys, "argv", ["yt-upload-collection", *argv])

        with (
            patch("youtube_automation.agents.collection_uploader.load_config", return_value=mock_config),
            patch("youtube_automation.agents.collection_uploader.CollectionUploader", return_value=uploader),
            patch("youtube_automation.agents.collection_uploader.ensure_collection_preflight") as mock_preflight,
            pytest.raises(SystemExit) as exc_info,
        ):
            collection_uploader.main()

        assert exc_info.value.code == 1
        assert "-c で対象を明示してください" in capsys.readouterr().out
        mock_preflight.assert_not_called()
        method.assert_not_called()

    def test_daily_check_skips_when_auto_detect_is_ambiguous(self, tmp_path, caplog):
        uploader, _ = _make_uploader_with_collection_mock(tmp_path)
        _write_workflow_state(
            tmp_path / "collections" / "planning" / "20260201-first-collection", phase="mastered", video_id=None
        )
        _write_workflow_state(
            tmp_path / "collections" / "planning" / "20260202-second-collection", phase="mastered", video_id=None
        )
        uploader.execute_next_step = MagicMock()

        uploader._daily_check_and_upload()

        uploader.execute_next_step.assert_not_called()
        assert "-c で対象を明示してください" in caplog.text


class TestDefaultPublishTimeFallback:
    """#1054: schedule_config 未指定時に channel youtube.default_publish_time を使う。"""

    def test_calculate_publish_at_uses_channel_default_when_schedule_disabled(self, tmp_path):
        uploader, _ = _make_uploader_with_schedule_config(
            tmp_path,
            {"schedule": {"timezone": "Asia/Tokyo"}},
        )

        with (
            patch("youtube_automation.agents._published_dates.load_config", return_value=MagicMock()),
            patch(
                "youtube_automation.agents._published_dates.resolve_default_publish_at",
                return_value="2099-01-01T20:00:00+09:00",
            ) as mock_resolve,
        ):
            result = uploader._calculate_publish_at()

        assert result == "2099-01-01T20:00:00+09:00"
        assert mock_resolve.called

    def test_auto_schedule_false_suppresses_channel_default(self, tmp_path):
        uploader, _ = _make_uploader_with_schedule_config(
            tmp_path,
            {"schedule": {"auto_schedule_enabled": False, "timezone": "Asia/Tokyo"}},
        )

        with patch("youtube_automation.agents._published_dates.resolve_default_publish_at") as mock_resolve:
            result = uploader._calculate_publish_at()

        assert result is None
        assert not mock_resolve.called


class TestPublishedDatesQuotaRecording:
    """Issue #2057: `_get_published_dates` が batch 回数と一致する quota を記録すること."""

    def _make_uploader_with_mock_service(self, tmp_path: Path):
        uploader, _ = _make_uploader_with_schedule_config(
            tmp_path,
            {"schedule": {"timezone": "Asia/Tokyo"}},
        )
        mock_service = MagicMock()
        uploader.youtube_service = mock_service
        return uploader, mock_service

    def _quota_calls(self, mock_log_quota) -> list[tuple[str, str, float]]:
        return [(c.args[0], c.args[1], c.args[2]) for c in mock_log_quota.call_args_list]

    def test_should_record_one_quota_entry_per_batch_request(self, tmp_path):
        """要件 2: batch 回数（search 1 + videos 1）と記録件数が一致する."""
        uploader, mock_service = self._make_uploader_with_mock_service(tmp_path)
        mock_service.search.return_value.list.return_value.execute.return_value = {"items": [{"id": {"videoId": "v1"}}]}
        mock_service.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "v1", "snippet": {"publishedAt": "2025-01-01T10:00:00Z"}, "status": {}}]
        }

        with patch("youtube_automation.agents._published_dates.cost_tracker.log_quota") as mock_log_quota:
            dates = uploader._get_published_dates()

        assert len(dates) == 1
        assert self._quota_calls(mock_log_quota) == [
            ("youtube-data-api", "search.list", 1),
            ("youtube-data-api", "videos.list", 1),
        ]

    def test_should_record_only_search_quota_when_channel_has_no_videos(self, tmp_path):
        """要件 4 相当: videos.list を実行しない場合はその quota を記録しない."""
        uploader, mock_service = self._make_uploader_with_mock_service(tmp_path)
        mock_service.search.return_value.list.return_value.execute.return_value = {"items": []}

        with patch("youtube_automation.agents._published_dates.cost_tracker.log_quota") as mock_log_quota:
            dates = uploader._get_published_dates()

        assert dates == set()
        assert self._quota_calls(mock_log_quota) == [("youtube-data-api", "search.list", 1)]
        mock_service.videos.return_value.list.assert_not_called()

    def test_should_record_quota_and_keep_fail_safe_on_api_error(self, tmp_path, caplog):
        """要件 3: API failure でも quota 記録後に既存 fail-safe（空 set + warning）を維持する."""
        uploader, mock_service = self._make_uploader_with_mock_service(tmp_path)
        mock_service.search.return_value.list.return_value.execute.side_effect = RuntimeError("boom")

        with (
            patch("youtube_automation.agents._published_dates.cost_tracker.log_quota") as mock_log_quota,
            caplog.at_level(logging.WARNING),
        ):
            dates = uploader._get_published_dates()

        assert dates == set()
        assert self._quota_calls(mock_log_quota) == [("youtube-data-api", "search.list", 1)]
        assert any(rec.levelno == logging.WARNING for rec in caplog.records)


class TestExecuteCompleteCollectionResume:
    """resumable upload session URI の tracking 連携を検証する.

    issue #381 (P0-5) の中核回帰テストを含む:
    - L4-7: 前回成功で URI クリア済みの tracking で再実行
    - L4-8: 1 回目失敗 → 2 回目で同一 URI で resume
    """

    def test_should_pass_persisted_resume_session_uri_to_uploader_when_tracking_has_one(self, tmp_path):
        """plan 要件 #4: tracking に URI があれば uploader にそのまま渡す."""
        # Given
        col, _ = _make_tracking_collection(tmp_path, resume_uri=_SESS_PREV)
        uploader, mock_inner = _make_uploader_with_collection_mock(tmp_path)
        mock_inner.upload_collection.return_value = {
            "complete_video": {
                "video_id": "V_OK",
                "video_url": "https://www.youtube.com/watch?v=V_OK",
                "title": "t",
                "file_path": "p",
            }
        }

        # When
        tracking = uploader._load_tracking(col)
        uploader._execute_complete_collection(col, tracking, publish_at=None)

        # Then
        call_kwargs = mock_inner.upload_collection.call_args.kwargs
        assert call_kwargs.get("resume_session_uri") == _SESS_PREV

    def test_should_pass_none_resume_session_uri_when_tracking_has_no_persisted_uri(self, tmp_path):
        """tracking に URI 無しなら uploader には None が渡る（フレッシュ実行）."""
        # Given
        col, _ = _make_tracking_collection(tmp_path, resume_uri=None)
        uploader, mock_inner = _make_uploader_with_collection_mock(tmp_path)
        mock_inner.upload_collection.return_value = {
            "complete_video": {
                "video_id": "V_FRESH",
                "video_url": "u",
                "title": "t",
                "file_path": "p",
            }
        }

        # When
        tracking = uploader._load_tracking(col)
        uploader._execute_complete_collection(col, tracking, publish_at=None)

        # Then
        call_kwargs = mock_inner.upload_collection.call_args.kwargs
        assert call_kwargs.get("resume_session_uri") is None

    def test_should_write_timezone_aware_upload_time(self, tmp_path):
        """Complete Collection 成功時の upload_time は schedule timezone 付き ISO 8601."""
        col, tracking_path = _make_tracking_collection(tmp_path, resume_uri=None)
        uploader, mock_inner = _make_uploader_with_schedule_config(
            tmp_path,
            {"schedule": {"timezone": "UTC"}},
        )
        mock_inner.upload_collection.return_value = {
            "complete_video": {
                "video_id": "V_TZ",
                "video_url": "u",
                "title": "t",
                "file_path": "p",
            }
        }

        tracking = uploader._load_tracking(col)
        uploader._execute_complete_collection(col, tracking, publish_at=None)

        saved = json.loads(tracking_path.read_text(encoding="utf-8"))
        upload_time = saved["complete_collection"]["upload_time"]
        dt = datetime.fromisoformat(upload_time)
        assert dt.tzinfo is not None
        assert dt.utcoffset() == timedelta(0)

    def test_should_update_workflow_upload_when_complete_collection_succeeds(self, tmp_path):
        """成功時は workflow-state.json の upload を tracking と同じ video_id/url/publish_at で更新する."""
        col, _ = _make_tracking_collection(tmp_path, resume_uri=None)
        uploader, mock_inner = _make_uploader_with_collection_mock(tmp_path)
        mock_inner.upload_collection.return_value = {
            "complete_video": {
                "video_id": "V_WORKFLOW",
                "video_url": "https://www.youtube.com/watch?v=V_WORKFLOW",
                "title": "t",
                "file_path": "p",
            }
        }

        tracking = uploader._load_tracking(col)
        uploader._execute_complete_collection(col, tracking, publish_at="2099-01-01T10:00:00+09:00")

        state = json.loads((col / "workflow-state.json").read_text(encoding="utf-8"))
        assert state["upload"] == {
            "video_id": "V_WORKFLOW",
            "video_url": "https://www.youtube.com/watch?v=V_WORKFLOW",
            "publish_at": "2099-01-01T10:00:00+09:00",
        }

    def test_should_distinguish_dedup_skip_and_keep_tracking_workflow_consistent_after_live_move(self, tmp_path):
        """dedup skip 時も live 移動後の tracking/workflow-state に既存 video_id を記録する."""
        col, _ = _make_tracking_collection(tmp_path, resume_uri=None)
        uploader, mock_inner = _make_uploader_with_collection_mock(tmp_path)
        uploader.config["collections_management"]["auto_move_to_live"] = True
        mock_inner.upload_collection.return_value = {
            "complete_video": {
                "video_id": "V_EXISTING",
                "video_url": "https://www.youtube.com/watch?v=V_EXISTING",
                "upload_source": "existing_video",
                "title": "t",
                "file_path": "p",
            }
        }

        tracking = uploader._load_tracking(col)
        result = uploader._execute_complete_collection(col, tracking, publish_at="2099-01-01T10:00:00+09:00")

        live_col = tmp_path / "collections" / "live" / col.name
        saved_tracking = json.loads(
            (live_col / "20-documentation" / "upload_tracking.json").read_text(encoding="utf-8")
        )
        saved_state = json.loads((live_col / "workflow-state.json").read_text(encoding="utf-8"))
        assert result["action"] == "complete_collection_dedup_skipped"
        assert saved_tracking["status"] == "completed"
        assert saved_tracking["complete_collection"]["video_id"] == "V_EXISTING"
        assert saved_tracking["complete_collection"]["upload_source"] == "existing_video"
        assert saved_state["stage"] == "live"
        assert saved_state["phase"] == "complete"
        assert saved_state["upload"] == {
            "video_id": "V_EXISTING",
            "video_url": "https://www.youtube.com/watch?v=V_EXISTING",
            "publish_at": "2099-01-01T10:00:00+09:00",
        }

    def test_should_persist_uri_to_tracking_when_on_session_uri_changed_is_invoked(self, tmp_path):
        """plan 要件 #1 + #2: コールバック発火直後に URI が tracking JSON に永続化される.

        upload 完了後のクリーンアップに混ざらないよう、side_effect 内で callback 発火直後の
        disk 状態をキャプチャして検証する（cleanup 検証は別ケースで分離）。
        """
        # Given
        col, tracking_path = _make_tracking_collection(tmp_path, resume_uri=None)
        uploader, mock_inner = _make_uploader_with_collection_mock(tmp_path)
        captured: dict[str, str | None] = {}

        def _side_effect(*args, **kwargs):
            kwargs["on_session_uri_changed"](_SESS_NEW)
            captured["uri"] = _read_resume_uri(tracking_path)
            # 失敗結果で halt（成功時の URI クリアと混ざらないように）
            return {"complete_video": {"error": "halt for assertion"}}

        mock_inner.upload_collection.side_effect = _side_effect

        # When
        tracking = uploader._load_tracking(col)
        uploader._execute_complete_collection(col, tracking, publish_at=None)

        # Then
        assert captured["uri"] == _SESS_NEW

    def test_should_clear_uri_from_tracking_when_on_upload_complete_is_invoked(self, tmp_path):
        """plan 要件 #6: on_upload_complete が発火したら tracking から URI を消す."""
        # Given: 初期に URI を持つ tracking
        col, tracking_path = _make_tracking_collection(tmp_path, resume_uri=_SESS_PREV)
        uploader, mock_inner = _make_uploader_with_collection_mock(tmp_path)

        def _side_effect(*args, **kwargs):
            kwargs["on_upload_complete"]()
            return {
                "complete_video": {
                    "video_id": "V_OK",
                    "video_url": "u",
                    "title": "t",
                    "file_path": "p",
                }
            }

        mock_inner.upload_collection.side_effect = _side_effect

        # When
        tracking = uploader._load_tracking(col)
        uploader._execute_complete_collection(col, tracking, publish_at=None)

        # Then: tracking 上の URI が消えている
        assert _read_resume_uri(tracking_path) is None

    def test_should_remove_uri_from_tracking_when_on_session_uri_changed_receives_none(self, tmp_path):
        """plan 要件 #7: on_session_uri_changed(None) で URI クリア（session 失効パス）."""
        # Given: 初期に URI を持つ tracking
        col, tracking_path = _make_tracking_collection(tmp_path, resume_uri=_SESS_PREV)
        uploader, mock_inner = _make_uploader_with_collection_mock(tmp_path)

        def _side_effect(*args, **kwargs):
            # session 失効 → クリア通知 → 失敗 result
            kwargs["on_session_uri_changed"](None)
            return {"complete_video": {"error": "session expired"}}

        mock_inner.upload_collection.side_effect = _side_effect

        # When
        tracking = uploader._load_tracking(col)
        uploader._execute_complete_collection(col, tracking, publish_at=None)

        # Then
        assert _read_resume_uri(tracking_path) is None

    def test_should_reload_tracking_before_persisting_uri_to_avoid_clobbering_concurrent_writes(self, tmp_path):
        """plan §162: コールバック内で `_load_tracking` を再ロードすることで並行書き込みを保持.

        side_effect 内で callback 発火直後の disk 状態をキャプチャし、callback が
        外部からの concurrent 書き込みを保持しているかを直接検証する
        （upload 後段のクリーンアップに干渉されないよう intermediate state を読む）。
        """
        # Given: 初期 tracking 無 URI
        col, tracking_path = _make_tracking_collection(tmp_path, resume_uri=None)
        uploader, mock_inner = _make_uploader_with_collection_mock(tmp_path)
        captured_cc: dict[str, dict] = {}

        def _side_effect(*args, **kwargs):
            # 1. 外部から並行的に tracking に別キーを書き込む（CollectionUploader の in-memory dict には反映されない）
            current = json.loads(tracking_path.read_text(encoding="utf-8"))
            current.setdefault("complete_collection", {})["concurrent_marker"] = "x"
            tracking_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
            # 2. on_session_uri_changed を発火し URI を永続化
            kwargs["on_session_uri_changed"](_SESS_NEW)
            # 3. callback 直後の disk 状態をキャプチャ（後段クリーンアップに干渉されない地点）
            captured_cc["state"] = json.loads(tracking_path.read_text(encoding="utf-8"))
            # 失敗結果で halt
            return {"complete_video": {"error": "halt for intermediate-state assertion"}}

        mock_inner.upload_collection.side_effect = _side_effect

        # When
        tracking = uploader._load_tracking(col)
        uploader._execute_complete_collection(col, tracking, publish_at=None)

        # Then: callback 内で reload してから書いていれば、両キーが同時に disk に残る
        cc = captured_cc["state"].get("complete_collection", {})
        assert cc.get("resume_session_uri") == _SESS_NEW
        assert cc.get("concurrent_marker") == "x"

    def test_should_not_reuse_stale_uri_after_successful_previous_upload(self, tmp_path):
        """plan 要件 #6 回帰: 前回成功で URI クリア済みの tracking で再実行しても URI は None."""
        # Given: 前回成功で URI クリア済みの tracking（=URI 無し、status pending に戻したとする）
        col, _ = _make_tracking_collection(tmp_path, resume_uri=None)
        uploader, mock_inner = _make_uploader_with_collection_mock(tmp_path)
        mock_inner.upload_collection.return_value = {
            "complete_video": {
                "video_id": "V_FRESH",
                "video_url": "u",
                "title": "t",
                "file_path": "p",
            }
        }

        # When
        tracking = uploader._load_tracking(col)
        uploader._execute_complete_collection(col, tracking, publish_at=None)

        # Then
        call_kwargs = mock_inner.upload_collection.call_args.kwargs
        assert call_kwargs.get("resume_session_uri") is None

    def test_should_resume_same_session_uri_on_retry_after_mid_upload_failure(self, tmp_path):
        """**issue #381 中核回帰**: 1 回目失敗 → 2 回目で同一 URI で resume."""
        # Given: 初回は URI 無し、upload 中 on_session_uri_changed で永続化 → 失敗
        col, tracking_path = _make_tracking_collection(tmp_path, resume_uri=None)
        uploader, mock_inner = _make_uploader_with_collection_mock(tmp_path)

        def _first_run(*args, **kwargs):
            kwargs["on_session_uri_changed"](_SESS_NEW)
            return {"complete_video": {"error": "network error mid-upload"}}

        mock_inner.upload_collection.side_effect = _first_run

        tracking_first = uploader._load_tracking(col)
        uploader._execute_complete_collection(col, tracking_first, publish_at=None)

        # 1 回目失敗で URI は tracking に残っているはず（precondition）
        assert _read_resume_uri(tracking_path) == _SESS_NEW

        # When: 2 回目を実行
        mock_inner.upload_collection.side_effect = None
        mock_inner.upload_collection.return_value = {
            "complete_video": {
                "video_id": "V_RESUMED",
                "video_url": "u",
                "title": "t",
                "file_path": "p",
            }
        }
        tracking_second = uploader._load_tracking(col)
        uploader._execute_complete_collection(col, tracking_second, publish_at=None)

        # Then: 2 回目は同一 URI で resume している
        second_call_kwargs = mock_inner.upload_collection.call_args.kwargs
        assert second_call_kwargs.get("resume_session_uri") == _SESS_NEW

    def test_should_clear_persisted_uri_when_uploader_returns_failure_due_to_session_expired(self, tmp_path):
        """plan 要件 #7 結合: session 失効 → URI クリア + 失敗結果の同時担保."""
        # Given: 初期 URI あり、uploader が session 失効でクリア通知 → 失敗
        col, tracking_path = _make_tracking_collection(tmp_path, resume_uri=_SESS_PREV)
        uploader, mock_inner = _make_uploader_with_collection_mock(tmp_path)

        def _side_effect(*args, **kwargs):
            kwargs["on_session_uri_changed"](None)
            return {"complete_video": {"error": "session expired"}}

        mock_inner.upload_collection.side_effect = _side_effect

        # When
        tracking = uploader._load_tracking(col)
        result = uploader._execute_complete_collection(col, tracking, publish_at=None)

        # Then
        assert _read_resume_uri(tracking_path) is None
        assert result["action"] == "complete_collection_failed"

    def test_should_not_mark_failed_and_returns_quota_exhausted_action_when_quota_error_raised(self, tmp_path):
        """plan 020 Step 3: QuotaExhaustedError はリトライ可能として非終端化する.

        tracking の complete_collection.status を "failed" にせず、resume URI
        （callback が既に永続化済み）を温存したまま次回実行に委ねる。
        """
        from youtube_automation.agents._collection_uploader_constants import (
            ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED,
        )
        from youtube_automation.utils.exceptions import QuotaExhaustedError

        col, tracking_path = _make_tracking_collection(tmp_path, resume_uri=None)
        uploader, mock_inner = _make_uploader_with_collection_mock(tmp_path)

        def _side_effect(*args, **kwargs):
            kwargs["on_session_uri_changed"](_SESS_NEW)
            raise QuotaExhaustedError("quota exceeded", retry_after_seconds=42.0)

        mock_inner.upload_collection.side_effect = _side_effect

        tracking = uploader._load_tracking(col)
        result = uploader._execute_complete_collection(col, tracking, publish_at=None)

        assert result["action"] == ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED
        assert result["details"]["retry_after_seconds"] == 42.0

        saved = json.loads(tracking_path.read_text(encoding="utf-8"))
        assert saved["complete_collection"].get("status") != "failed"
        # callback が既に永続化した resume URI は温存されている
        assert saved["complete_collection"]["resume_session_uri"] == _SESS_NEW


class TestShowPlanPrivacyDisplay:
    """#1472: --plan の公開設定表示は実効 privacy_status（youtube.json）を反映する。

    schedule 無効時に固定 "即時公開 (public)" を出すと、unlisted / private 運用
    チャンネルで表示と実効値が乖離する（FB 起点バグ）。
    """

    def _plan_output(self, tmp_path, capsys, privacy_status):
        uploader, _ = _make_uploader_with_schedule_config(
            tmp_path,
            {"schedule": {"auto_schedule_enabled": False, "timezone": "Asia/Tokyo"}},
        )
        config_mock = MagicMock()
        config_mock.youtube.api.privacy_status = privacy_status
        with patch(
            "youtube_automation.agents.collection_uploader.load_config",
            return_value=config_mock,
        ):
            uploader.show_plan(tmp_path / "collections" / "planning" / "Test Collection")
        return capsys.readouterr().out

    def test_unlisted_channel_shows_effective_privacy_not_fixed_public(self, tmp_path, capsys):
        out = self._plan_output(tmp_path, capsys, "unlisted")
        assert "📅 公開設定: 限定公開 (unlisted)" in out
        assert "即時公開 (public)" not in out
        assert "youtube.json::privacy_status" in out

    def test_private_channel_shows_effective_privacy(self, tmp_path, capsys):
        out = self._plan_output(tmp_path, capsys, "private")
        assert "📅 公開設定: 非公開 (private)" in out
        assert "即時公開 (public)" not in out

    def test_public_channel_keeps_immediate_publish_wording(self, tmp_path, capsys):
        """skill docs（test_skill_docs_consistency）が例示する文字列を維持する。"""
        out = self._plan_output(tmp_path, capsys, "public")
        assert "📅 公開設定: 即時公開 (public)" in out

    def test_plan_separates_daily_buckets_from_unit_pool(self, tmp_path, capsys):
        out = self._plan_output(tmp_path, capsys, "private")

        assert "独立日次 bucket: videos.insert 1/100 calls" in out
        assert "独立日次 bucket: search.list 2/100 calls" in out
        assert "unit pool: thumbnails.set 1 × 50 units" in out
        assert "unit pool: playlistItems.insert 1 × 50 units" in out
        assert "unit pool 合計: 102/10,000 units" in out
        assert "284/10,000" not in out


def test_execute_collection_suppresses_lower_default_publish_fallback_when_schedule_disabled(tmp_path):
    col, _ = _make_tracking_collection(tmp_path, resume_uri=None)
    uploader, mock_inner = _make_uploader_with_schedule_config(
        tmp_path,
        {"schedule": {"auto_schedule_enabled": False, "timezone": "Asia/Tokyo"}},
    )
    mock_inner.upload_collection.return_value = {
        "complete_video": {
            "video_id": "V_NO_FALLBACK",
            "video_url": "https://www.youtube.com/watch?v=V_NO_FALLBACK",
            "title": "t",
            "file_path": "p",
        }
    }

    tracking = uploader._load_tracking(col)
    uploader._execute_complete_collection(col, tracking, publish_at=None)

    call_kwargs = mock_inner.upload_collection.call_args.kwargs
    assert call_kwargs["publish_at"] is None
    assert call_kwargs["apply_default_publish_at"] is False


class TestScheduleConfigPrivacyStatusDeprecation:
    """#1472: schedule_config.json::upload_settings.privacy_status は未参照。

    実効値は config/channel/youtube.json::privacy_status に一本化し、
    残存設定には警告で案内する。
    """

    def test_warns_when_legacy_privacy_status_present_in_schedule_config(self, tmp_path, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="youtube_automation.agents.collection_uploader"):
            _make_uploader_with_schedule_config(
                tmp_path,
                {"upload_settings": {"privacy_status": "unlisted"}},
            )
        assert "upload_settings.privacy_status は参照されません" in caplog.text
        assert "youtube.json::privacy_status" in caplog.text

    def test_default_config_has_no_privacy_status_and_no_warning(self, tmp_path, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="youtube_automation.agents.collection_uploader"):
            uploader, _ = _make_uploader_with_collection_mock(tmp_path)
        assert "privacy_status" not in uploader.config["upload_settings"]
        assert "upload_settings.privacy_status" not in caplog.text


class TestTrackingIOAtomicity:
    """plan 020 Step 1/2: tracking JSON のアトミック書き込み・破損検出を検証する。"""

    def test_save_tracking_leaves_no_tmp_file_and_roundtrips(self, tmp_path):
        col, tracking_path = _make_tracking_collection(tmp_path, resume_uri=None)
        uploader, _ = _make_uploader_with_collection_mock(tmp_path)

        tracking = uploader._load_tracking(col)
        tracking["status"] = "updated"
        uploader._save_tracking(col, tracking)

        tmp_path_file = tracking_path.with_suffix(tracking_path.suffix + ".tmp")
        assert not tmp_path_file.exists()
        saved = json.loads(tracking_path.read_text(encoding="utf-8"))
        assert saved["status"] == "updated"

    def test_load_tracking_returns_none_and_quarantines_corrupt_file(self, tmp_path):
        col, tracking_path = _make_tracking_collection(tmp_path, resume_uri=None)
        tracking_path.write_text("{truncated", encoding="utf-8")
        uploader, _ = _make_uploader_with_collection_mock(tmp_path)

        result = uploader._load_tracking(col)

        assert result is None
        corrupt_path = tracking_path.with_suffix(".json.corrupt")
        assert corrupt_path.exists()
        assert corrupt_path.read_text(encoding="utf-8") == "{truncated"
        assert not tracking_path.exists()
