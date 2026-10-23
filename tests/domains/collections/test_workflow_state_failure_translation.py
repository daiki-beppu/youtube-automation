"""workflow-state の失敗種別を各呼び出し元が利用者向けの例外へ変換する契約テスト。"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from youtube_automation.application.metadata.service import (
    _load_metadata_workflow_state,
    _persist_track_display_names,
)
from youtube_automation.commands.media import check_raw_master, generate_videos_batch
from youtube_automation.commands.media.apply_rain_layers import _update_workflow_state_raw_master
from youtube_automation.commands.thumbnail.auto_select_thumbnail import load_workflow_state
from youtube_automation.commands.uploads import wf_batch
from youtube_automation.core.errors import ConfigError, ValidationError, WorkflowStateError
from youtube_automation.domains.collections.paths import CollectionPaths
from youtube_automation.domains.distrokid.preparation import write_release_date
from youtube_automation.domains.distrokid.release import _read_release_date
from youtube_automation.domains.suno.downloaded.workflow import update_workflow_state_downloaded
from youtube_automation.domains.suno.prompt_resolution import _read_workflow_track_count
from youtube_automation.domains.suno.selection import (
    SelectionResult,
    WorkflowStateSnapshot,
    _read_workflow_state,
    _sync_workflow_state_music_pair_selection,
)
from youtube_automation.domains.uploads.master_video import resolve_master_video
from youtube_automation.domains.uploads.preflight import _validate_scene_phrases

CollectionCall = Callable[[Path], object]


def _state_path(collection: Path) -> Path:
    return CollectionPaths(collection).workflow_state_path


@pytest.fixture
def collection(tmp_path: Path) -> Path:
    directory = tmp_path / "collection"
    (directory / "01-master").mkdir(parents=True)
    (directory / "01-master" / "Collection-Master.mp4").write_bytes(b"video")
    (directory / "01-master" / "raw.wav").write_bytes(b"audio")
    return directory


def _apply_raw_master(collection: Path) -> None:
    check_raw_master.apply_raw_master(collection, "raw.wav")


def _sync_music_pair_selection(collection: Path) -> None:
    result = SelectionResult([], [], [], [], [], [], {}, collection / "selection.log")
    _sync_workflow_state_music_pair_selection(
        WorkflowStateSnapshot(_state_path(collection)), result, incomplete_downloads=[1]
    )


def _record_downloaded(collection: Path) -> None:
    update_workflow_state_downloaded(collection, file_count=1, prompt_entries_reader=lambda _directory: [])


WRITERS: dict[str, CollectionCall] = {
    "distrokid.write_release_date": lambda c: write_release_date(_state_path(c), "2026-01-02"),
    "suno.selection.sync": _sync_music_pair_selection,
    "suno.downloaded": _record_downloaded,
    "media.generate_videos_batch": generate_videos_batch._update_workflow_state,
    "media.check_raw_master.apply": _apply_raw_master,
    "metadata.persist_track_display_names": lambda c: _persist_track_display_names(_state_path(c), {"01.wav": "Song"}),
}

READ_FAILURE_TRANSLATIONS: dict[str, tuple[type[Exception], str]] = {
    "distrokid.write_release_date": (ConfigError, "workflow-state.json を読み取れませんでした"),
    "suno.selection.sync": (ValidationError, "workflow-state.json を読み取れませんでした"),
    "suno.downloaded": (ValueError, "invalid workflow-state.json"),
    "media.generate_videos_batch": (ValidationError, "workflow-state.json を読めません"),
    "media.check_raw_master.apply": (ValidationError, "workflow-state.json のパースに失敗"),
    "metadata.persist_track_display_names": (ValidationError, "workflow-state.json を読めません"),
}

ROOT_MESSAGE = "root は object である必要があります"
INVALID_HANDOFF_STATE = '{"handoff": {"point": "unknown"}}'
NON_OBJECT_ROOT_TRANSLATIONS: dict[str, tuple[CollectionCall, type[Exception], str]] = {
    "distrokid.write_release_date": (
        WRITERS["distrokid.write_release_date"],
        ConfigError,
        "トップレベルが object ではありません",
    ),
    "distrokid.release_date": (
        lambda c: _read_release_date(CollectionPaths(c)),
        ConfigError,
        "トップレベルが object ではありません",
    ),
    "suno.track_count": (
        lambda c: _read_workflow_track_count(_state_path(c)),
        ConfigError,
        "トップレベルは object である必要があります",
    ),
    "uploads.resolve_master_video": (resolve_master_video, ValidationError, ROOT_MESSAGE),
    "suno.selection.read": (lambda c: _read_workflow_state(_state_path(c)), ValidationError, ROOT_MESSAGE),
    "thumbnail.load_workflow_state": (lambda c: load_workflow_state(_state_path(c)), ValidationError, ROOT_MESSAGE),
    "uploads.wf_batch": (lambda c: wf_batch._load_state(_state_path(c)), ValidationError, ROOT_MESSAGE),
    "media.apply_rain_layers": (
        lambda c: _update_workflow_state_raw_master(_state_path(c), "raw.wav"),
        ValidationError,
        ROOT_MESSAGE,
    ),
    "media.generate_videos_batch.read": (
        lambda c: generate_videos_batch._read_state(_state_path(c)),
        ValidationError,
        ROOT_MESSAGE,
    ),
    "media.check_raw_master.read": (
        lambda c: check_raw_master._load_state(_state_path(c)),
        ValidationError,
        ROOT_MESSAGE,
    ),
    "media.check_raw_master.apply": (_apply_raw_master, ValidationError, ROOT_MESSAGE),
    "metadata.load": (lambda c: _load_metadata_workflow_state(_state_path(c)), ValidationError, ROOT_MESSAGE),
    "metadata.persist_track_display_names": (
        WRITERS["metadata.persist_track_display_names"],
        ValidationError,
        ROOT_MESSAGE,
    ),
}


@pytest.mark.parametrize("caller", sorted(WRITERS))
def test_write_failure_propagates_the_os_error(caller: str, collection: Path, monkeypatch) -> None:
    _state_path(collection).write_text("{}", encoding="utf-8")
    disk_full = OSError(28, "No space left on device")

    def fail_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        raise disk_full

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError) as exc_info:
        WRITERS[caller](collection)

    assert exc_info.value is disk_full


@pytest.mark.parametrize("caller", sorted(WRITERS))
def test_read_os_failure_is_not_reported_as_a_write_failure(caller: str, collection: Path, monkeypatch) -> None:
    state_path = _state_path(collection)
    state_path.write_text("{}", encoding="utf-8")
    real_read_text = Path.read_text

    def fail_state_read(path: Path, *args: object, **kwargs: object) -> str:
        if path == state_path:
            raise PermissionError(13, "Permission denied")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_state_read)
    expected_type, expected_message = READ_FAILURE_TRANSLATIONS[caller]

    with pytest.raises(expected_type, match=expected_message) as exc_info:
        WRITERS[caller](collection)

    assert not isinstance(exc_info.value, OSError)


@pytest.mark.parametrize("caller", sorted(NON_OBJECT_ROOT_TRANSLATIONS))
def test_non_object_root_is_reported_with_the_callers_root_message(caller: str, collection: Path) -> None:
    _state_path(collection).write_text("[]", encoding="utf-8")
    call, expected_type, expected_message = NON_OBJECT_ROOT_TRANSLATIONS[caller]

    with pytest.raises(expected_type, match=expected_message):
        call(collection)


@pytest.mark.parametrize("caller", sorted(NON_OBJECT_ROOT_TRANSLATIONS))
def test_other_invalid_state_is_not_reported_as_a_non_object_root(caller: str, collection: Path) -> None:
    _state_path(collection).write_text(INVALID_HANDOFF_STATE, encoding="utf-8")
    call, expected_type, root_message = NON_OBJECT_ROOT_TRANSLATIONS[caller]

    with pytest.raises(expected_type) as exc_info:
        call(collection)

    assert root_message not in str(exc_info.value)


def test_preflight_reports_non_object_root_as_an_issue(collection: Path) -> None:
    _state_path(collection).write_text("[]", encoding="utf-8")

    assert _validate_scene_phrases(CollectionPaths(collection), ["ja"]) == [f"workflow-state.json の {ROOT_MESSAGE}"]


def test_preflight_propagates_other_invalid_state(collection: Path) -> None:
    _state_path(collection).write_text(INVALID_HANDOFF_STATE, encoding="utf-8")

    with pytest.raises(WorkflowStateError):
        _validate_scene_phrases(CollectionPaths(collection), ["ja"])


@pytest.mark.parametrize(
    ("call", "section", "expected_type", "expected_message"),
    [
        (
            lambda c: _read_release_date(CollectionPaths(c)),
            "planning",
            ConfigError,
            "planning が object ではありません",
        ),
        (resolve_master_video, "assets", ValidationError, "::assets は object である必要があります"),
    ],
    ids=["distrokid.release_date", "uploads.resolve_master_video"],
)
def test_non_object_section_is_reported_with_the_callers_section_message(
    call: CollectionCall, section: str, expected_type: type[Exception], expected_message: str, collection: Path
) -> None:
    _state_path(collection).write_text(f'{{"{section}": []}}', encoding="utf-8")

    with pytest.raises(expected_type, match=expected_message):
        call(collection)


@pytest.mark.parametrize(
    ("call", "expected_message"),
    [
        (lambda c: _read_workflow_state(_state_path(c)), "workflow-state.json must not be a symlink"),
        (lambda c: load_workflow_state(_state_path(c)), "シンボリックリンクは指定できません"),
    ],
    ids=["suno.selection.read", "thumbnail.load_workflow_state"],
)
def test_symlinked_state_is_reported_with_the_callers_symlink_message(
    call: CollectionCall, expected_message: str, collection: Path
) -> None:
    target = collection / "actual.json"
    target.write_text("{}", encoding="utf-8")
    _state_path(collection).symlink_to(target)

    with pytest.raises(ValidationError, match=expected_message):
        call(collection)


def test_selection_reports_a_directory_state_path_as_not_a_file(collection: Path) -> None:
    _state_path(collection).mkdir()

    with pytest.raises(ValidationError, match="workflow-state.json は file である必要があります"):
        _read_workflow_state(_state_path(collection))
