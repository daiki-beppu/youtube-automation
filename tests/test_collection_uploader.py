"""
CollectionUploader のユニットテスト

テスト対象: agents/collection_uploader.py

#77 回帰テスト: `_assign_to_playlists()` の import パス誤りで
プレイリスト自動追加が常時失敗していたバグを検出するためのテスト。
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
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

    def test_execute_next_step_suppresses_downstream_default_when_auto_schedule_false(self, tmp_path):
        col, _ = _make_tracking_collection(tmp_path)
        uploader, mock_inner = _make_uploader_with_schedule_config(
            tmp_path,
            {"schedule": {"auto_schedule_enabled": False, "timezone": "Asia/Tokyo"}},
        )
        mock_inner.upload_collection.return_value = {
            "complete_video": {
                "video_id": "V_IMMEDIATE",
                "video_url": "https://www.youtube.com/watch?v=V_IMMEDIATE",
                "title": "t",
                "file_path": "p",
            }
        }

        with patch("youtube_automation.agents._published_dates.resolve_default_publish_at") as mock_resolve:
            uploader.execute_next_step(col)

        call_kwargs = mock_inner.upload_collection.call_args.kwargs
        assert call_kwargs["publish_at"] is None
        assert call_kwargs["apply_default_publish_at"] is False
        assert not mock_resolve.called


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
