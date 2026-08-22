"""workflow-state document object の契約テスト。"""

from __future__ import annotations

import json
import multiprocessing
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from youtube_automation.core.errors import AutomationError, WorkflowStateError, WorkflowStateSectionTypeError
from youtube_automation.domains.collections.workflow_state import WorkflowState, read, read_or_none, update
from youtube_automation.infrastructure.filesystem import JSONValue


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _increment_in_process(path: Path, entered, release) -> None:
    def increment(state: WorkflowState) -> None:
        current = state["counter"]
        if isinstance(current, bool) or not isinstance(current, int):
            raise AssertionError("counter must be an integer")
        entered.set()
        release.wait()
        state["counter"] = current + 1

    update(path, increment)


def test_read_returns_typed_sections_and_compatible_accessors(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(
        state_path,
        {
            "phase": "prepared",
            "stage": "planning",
            "planning": {"music": {"engine": "suno"}},
            "assets": {"thumbnail": False, "description": True},
            "thumbnail": {"approved": True},
            "description": {"generated": False},
            "upload": {"video_id": "video-1", "video_url": None, "publish_at": None},
        },
    )

    state = read(state_path)

    assert isinstance(state, WorkflowState)
    assert state.phase == "prepared"
    assert state.stage == "planning"
    assert state.assets is not None
    assert state.assets.thumbnail is False
    assert state.upload is not None
    assert state.upload.video_id == "video-1"
    assert state.thumbnail_approved is True
    assert state.description_generated is True
    assert state.music_engine == "suno"


def test_thumbnail_approval_write_uses_canonical_asset_and_removes_legacy_field(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(
        state_path,
        {
            "assets": {"thumbnail": False, "future_asset": "keep"},
            "thumbnail": {"approved": True, "future_field": "keep"},
            "future_section": {"keep": True},
        },
    )

    update(state_path, lambda state: state.set_thumbnail_approved(False))

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["assets"] == {"thumbnail": False, "future_asset": "keep"}
    assert persisted["thumbnail"] == {"future_field": "keep"}
    assert persisted["future_section"] == {"keep": True}
    assert read(state_path).thumbnail_approved is False


def test_thumbnail_approval_write_creates_assets_and_drops_empty_legacy_section(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(state_path, {"thumbnail": {"approved": False}})

    update(state_path, lambda state: state.set_thumbnail_approved(True))

    assert json.loads(state_path.read_text(encoding="utf-8")) == {"assets": {"thumbnail": True}}


def test_description_completion_write_uses_canonical_asset_and_removes_legacy_field(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(
        state_path,
        {
            "assets": {"description": False, "future_asset": "keep"},
            "description": {"generated": True, "future_field": "keep"},
            "future_section": {"keep": True},
        },
    )

    update(state_path, lambda state: state.set_description_generated(False))

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["assets"] == {"description": False, "future_asset": "keep"}
    assert persisted["description"] == {"future_field": "keep"}
    assert persisted["future_section"] == {"keep": True}
    assert read(state_path).description_generated is False


def test_description_completion_write_creates_assets_and_drops_empty_legacy_section(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(state_path, {"description": {"generated": False}})

    update(state_path, lambda state: state.set_description_generated(True))

    assert json.loads(state_path.read_text(encoding="utf-8")) == {"assets": {"description": True}}


def test_description_completion_reads_legacy_state_through_compatibility_accessor(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(state_path, {"assets": {"description": False}, "description": {"generated": True}})

    state = read(state_path)

    assert state.description_generated is True


@pytest.mark.parametrize("value", [None, "10-assets/thumbnail.jpg", 1])
def test_assets_thumbnail_rejects_non_boolean_values(value: JSONValue) -> None:
    payload: dict[str, JSONValue] = {"assets": {"thumbnail": value}}
    state = WorkflowState(payload)

    with pytest.raises(WorkflowStateError, match=r"assets\.thumbnail must be a boolean"):
        assert state.assets is not None and state.assets.thumbnail


def test_update_preserves_unknown_keys_during_round_trip(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    unknown = {"nested": [1, {"future": True}]}
    _write(state_path, {"phase": "planning", "future_section": unknown})

    updated = update(state_path, lambda state: setattr(state, "phase", "prepared"))

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert updated.phase == "prepared"
    assert persisted["phase"] == "prepared"
    assert persisted["future_section"] == unknown


def test_record_cloud_handoff_changes_phase_and_keeps_only_manifest_reference(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(
        state_path,
        {
            "phase": "prepared",
            "planning": {"music": {"engine": "suno"}},
            "assets": {"music_downloaded": True},
            "handoff": {"future": "keep"},
            "future_section": {"keep": True},
        },
    )

    updated = update(
        state_path,
        lambda state: state.record_cloud_handoff(
            point="suno_download",
            manifest_key="002ch/sample/suno-download/manifest.json",
            root_sha256="a" * 64,
        ),
    )

    assert updated.phase == "cloud_owned"
    assert updated.handoff is not None
    assert updated.handoff.owner == "cloud"
    assert updated.handoff.manifest_key == "002ch/sample/suno-download/manifest.json"
    assert updated.handoff.root_sha256 == "a" * 64
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["handoff"] == {
        "future": "keep",
        "point": "suno_download",
        "owner": "cloud",
        "manifest_key": "002ch/sample/suno-download/manifest.json",
        "root_sha256": "a" * 64,
    }
    assert "files" not in persisted["handoff"]
    assert persisted["future_section"] == {"keep": True}


def test_record_cloud_handoff_is_idempotent_but_rejects_conflicting_reference() -> None:
    state = WorkflowState(
        {
            "phase": "prepared",
            "planning": {"music": {"engine": "suno"}},
            "assets": {"music_downloaded": True},
        }
    )

    state.record_cloud_handoff(
        point="suno_download",
        manifest_key="002ch/sample/suno-download/manifest.json",
        root_sha256="b" * 64,
    )
    state.record_cloud_handoff(
        point="suno_download",
        manifest_key="002ch/sample/suno-download/manifest.json",
        root_sha256="b" * 64,
    )

    with pytest.raises(WorkflowStateError, match="different manifest"):
        state.record_cloud_handoff(
            point="suno_download",
            manifest_key="002ch/sample/suno-download/manifest.json",
            root_sha256="c" * 64,
        )


@pytest.mark.parametrize(
    ("payload", "manifest_key", "root_sha256", "message"),
    [
        (
            {"phase": "planning", "planning": {"music": {"engine": "suno"}}, "assets": {"music_downloaded": True}},
            "002ch/sample/suno-download/manifest.json",
            "a" * 64,
            "prepared",
        ),
        (
            {"phase": "prepared", "planning": {"music": {"engine": "suno"}}, "assets": {"music_downloaded": False}},
            "002ch/sample/suno-download/manifest.json",
            "a" * 64,
            "music_downloaded",
        ),
        (
            {"phase": "prepared", "planning": {"music": {"engine": "suno"}}, "assets": {"music_downloaded": True}},
            "../manifest.json",
            "a" * 64,
            "manifest_key",
        ),
        (
            {"phase": "prepared", "planning": {"music": {"engine": "suno"}}, "assets": {"music_downloaded": True}},
            "manifest.json",
            "a" * 64,
            "manifest_key",
        ),
        (
            {"phase": "prepared", "planning": {"music": {"engine": "suno"}}, "assets": {"music_downloaded": True}},
            "002ch/sample/suno-download/manifest.json",
            "not-a-sha",
            "root_sha256",
        ),
    ],
)
def test_record_cloud_handoff_fails_closed_before_mutation(
    payload: dict[str, JSONValue],
    manifest_key: str,
    root_sha256: str,
    message: str,
) -> None:
    state = WorkflowState(payload)
    before = state.to_dict()

    with pytest.raises(WorkflowStateError, match=message):
        state.record_cloud_handoff(
            point="suno_download",
            manifest_key=manifest_key,
            root_sha256=root_sha256,
        )

    assert state.to_dict() == before


def test_record_distrokid_submission_preserves_first_completion_and_unknown_fields() -> None:
    state = WorkflowState(
        {
            "human_tasks": {
                "future": {"keep": True},
                "distrokid_submission": {"future": "keep"},
            },
            "unknown": {"keep": True},
        }
    )

    state.record_distrokid_submission("2026-08-16T01:02:03.000Z")

    assert state.distrokid_submission_completed_at == "2026-08-16T01:02:03.000Z"
    assert state.to_dict() == {
        "human_tasks": {
            "future": {"keep": True},
            "distrokid_submission": {
                "future": "keep",
                "completed_at": "2026-08-16T01:02:03.000Z",
            },
        },
        "unknown": {"keep": True},
    }

    state.record_distrokid_submission("2026-08-17T04:05:06.000Z")

    assert state.distrokid_submission_completed_at == "2026-08-16T01:02:03.000Z"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"human_tasks": []}, "human_tasks must be an object"),
        (
            {"human_tasks": {"distrokid_submission": True}},
            "human_tasks.distrokid_submission must be an object",
        ),
        (
            {"human_tasks": {"distrokid_submission": {"completed_at": True}}},
            "human_tasks.distrokid_submission.completed_at must be a string",
        ),
        (
            {"human_tasks": {"distrokid_submission": {"completed_at": "not-a-time"}}},
            "human_tasks.distrokid_submission.completed_at must be an ISO 8601 datetime",
        ),
        (
            {"human_tasks": {"distrokid_submission": {"completed_at": "2026-08-16T01:02:03"}}},
            "human_tasks.distrokid_submission.completed_at must include a timezone",
        ),
    ],
)
def test_distrokid_submission_state_fails_closed_on_invalid_known_shape(
    payload: dict[str, JSONValue],
    message: str,
) -> None:
    with pytest.raises(WorkflowStateError, match=message):
        WorkflowState(payload)


def test_update_creates_missing_document_under_the_same_contract(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"

    created = update(state_path, lambda state: setattr(state, "phase", "planning"))

    assert created.phase == "planning"
    assert read(state_path).phase == "planning"


@pytest.mark.parametrize("payload", ["{broken", "[]", "null"])
def test_read_rejects_broken_json_and_non_object_roots(tmp_path: Path, payload: str) -> None:
    state_path = tmp_path / "workflow-state.json"
    state_path.write_text(payload, encoding="utf-8")

    with pytest.raises(WorkflowStateError):
        read(state_path)


def test_read_and_read_or_none_distinguish_missing_file(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"

    with pytest.raises(WorkflowStateError):
        read(state_path)
    assert read_or_none(state_path) is None


def test_read_and_read_or_none_reject_symlink(tmp_path: Path) -> None:
    target = tmp_path / "actual.json"
    state_path = tmp_path / "workflow-state.json"
    _write(target, {"phase": "planning"})
    state_path.symlink_to(target)

    with pytest.raises(WorkflowStateError):
        read(state_path)
    with pytest.raises(WorkflowStateError):
        read_or_none(state_path)


def test_read_rejects_non_object_known_section(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(state_path, {"assets": []})

    with pytest.raises(WorkflowStateError):
        read(state_path)


def test_upload_read_accessors_return_typed_values_and_keep_unknown_fields(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(
        state_path,
        {
            "theme": "Rainy Jazz",
            "collection_name": "Rainy Jazz Collection",
            "title_activity": "focus",
            "track_count": 12,
            "created_at": "2026-08-16T09:00:00+09:00",
            "video_id": "legacy-video",
            "upload": {"video_id": "canonical-video"},
            "planning": {
                "activities": "focus",
                "scene_emoji": "🌧️",
                "publish_target_at": "2026-09-01T08:00:00+09:00",
                "final_title_en": "Rainy Focus",
                "final_title": "雨の集中時間",
                "music": {"patterns": {"a": {"display_name": "Rain Window"}}},
            },
            "assets": {"video": "master.mp4"},
            "scene_phrases": {"en": "continuous focus mix"},
            "title_template_check": {"allow_volume_patterns": True},
            "track_display_names": {"01-rain.wav": "Rain Window"},
            "post_upload": {"shorts": [{"short_num": 1, "video_id": "short-1"}]},
            "future_section": {"enabled": True},
        },
    )

    state = read(state_path)

    assert state.theme == "Rainy Jazz"
    assert state.planning is not None
    assert state.planning.activities == "focus"
    assert state.planning.scene_emoji == "🌧️"
    assert state.planning.music is not None
    assert state.planning.music.patterns == {"a": {"display_name": "Rain Window"}}
    assert state.scene_phrases == {"en": "continuous focus mix"}
    assert state.allow_volume_patterns is True
    assert state.collection_name == "Rainy Jazz Collection"
    assert state.title_activity == "focus"
    assert state.track_count == 12
    assert state.created_at == "2026-08-16T09:00:00+09:00"
    assert state.upload is not None
    assert state.upload.video_id == "canonical-video"
    assert state["video_id"] == "legacy-video"
    with pytest.raises(AttributeError):
        _legacy_video_id = state.video_id
    assert state.planning.publish_target_at == "2026-09-01T08:00:00+09:00"
    assert state.planning.final_title_en == "Rainy Focus"
    assert state.planning.final_title == "雨の集中時間"
    assert state.assets is not None
    assert state.assets["video"] == "master.mp4"
    with pytest.raises(AttributeError):
        _legacy_video = state.assets.video
    assert state.track_display_names == {"01-rain.wav": "Rain Window"}
    assert state.post_upload is not None
    assert state.post_upload.shorts == [{"short_num": 1, "video_id": "short-1"}]
    assert state["future_section"] == {"enabled": True}


def test_update_preserves_unknown_legacy_asset_fields_without_typed_accessors(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(state_path, {"phase": "planning", "assets": {"video": "legacy.mp4", "future": {"keep": True}}})

    update(state_path, lambda state: setattr(state, "phase", "prepared"))

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["assets"] == {"video": "legacy.mp4", "future": {"keep": True}}


@pytest.mark.parametrize(
    "payload, access",
    [
        ({"track_count": "12"}, lambda state: state.track_count),
        ({"track_count": True}, lambda state: state.track_count),
        (
            {"planning": {"publish_target_at": 20260901}},
            lambda state: state.planning.publish_target_at,
        ),
    ],
)
def test_domain_reader_accessors_reject_wrong_types(
    tmp_path: Path,
    payload: dict[str, object],
    access,
) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(state_path, payload)

    with pytest.raises(WorkflowStateError):
        access(read(state_path))


def test_compatible_music_engine_accessor_rejects_conflicting_values(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(state_path, {"music_engine": "suno", "planning": {"music": {"engine": "lyria"}}})

    with pytest.raises(WorkflowStateError):
        _engine = read(state_path).music_engine


@pytest.mark.parametrize(
    "payload",
    [
        {"music_engine": "lyria"},
        {"planning": {"music": {"engine": "lyria"}}},
        {"music_engine": "lyria", "planning": {"music": {"engine": "lyria"}}},
    ],
)
def test_music_engine_accessor_reads_canonical_and_legacy_shapes(
    tmp_path: Path,
    payload: dict[str, JSONValue],
) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(state_path, payload)

    assert read(state_path).music_engine == "lyria"


def test_music_engine_accepts_minimax_in_owner_schema(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(state_path, {"planning": {"music": {"engine": "minimax"}}})

    assert read(state_path).music_engine == "minimax"


def test_music_planning_exposes_non_negative_expected_file_count(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(state_path, {"planning": {"music": {"expected_file_count": 4}}})

    state = read(state_path)

    assert state.planning is not None
    assert state.planning.music is not None
    assert state.planning.music.expected_file_count == 4


@pytest.mark.parametrize("value", [True, -1, "4", 4.5])
def test_music_planning_rejects_invalid_expected_file_count(tmp_path: Path, value: object) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(state_path, {"planning": {"music": {"expected_file_count": value}}})

    with pytest.raises(WorkflowStateError, match="expected_file_count"):
        state = read(state_path)
        assert state.planning is not None
        assert state.planning.music is not None
        _expected = state.planning.music.expected_file_count


def test_update_keeps_existing_file_when_callback_fails(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    original = '{"phase":"planning","counter":0}'
    state_path.write_text(original, encoding="utf-8")

    def fail_after_mutation(state: WorkflowState) -> None:
        state["counter"] = 1
        raise RuntimeError("update failed")

    with pytest.raises(RuntimeError, match="update failed"):
        update(state_path, fail_after_mutation)

    assert state_path.read_text(encoding="utf-8") == original


def test_update_keeps_existing_file_and_cleans_temp_when_replace_fails(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "workflow-state.json"
    original = '{"phase":"planning"}'
    state_path.write_text(original, encoding="utf-8")

    def fail_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(WorkflowStateError):
        update(state_path, lambda state: setattr(state, "phase", "prepared"))

    assert state_path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".workflow-state.*.tmp")) == []


def test_update_reports_replace_and_temp_cleanup_failures(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "workflow-state.json"
    original = '{"phase":"planning"}'
    state_path.write_text(original, encoding="utf-8")
    real_unlink = Path.unlink
    temporary: Path | None = None

    def fail_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        raise OSError("replace failed")

    def fail_temporary_cleanup(path: Path, *, missing_ok: bool = False) -> None:
        nonlocal temporary
        if path.name.startswith(".workflow-state."):
            temporary = path
            raise OSError("cleanup failed")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(os, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_temporary_cleanup)

    with pytest.raises(WorkflowStateError, match="replace failed.*cleanup failed"):
        update(state_path, lambda state: setattr(state, "phase", "prepared"))

    assert state_path.read_text(encoding="utf-8") == original
    assert temporary is not None
    real_unlink(temporary)


def test_update_serializes_processes_without_losing_changes(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow-state.json"
    _write(state_path, {"counter": 0})
    context = multiprocessing.get_context("spawn")
    first_entered = context.Event()
    second_entered = context.Event()
    release_first = context.Event()
    release_second = context.Event()
    first = context.Process(target=_increment_in_process, args=(state_path, first_entered, release_first))
    second = context.Process(target=_increment_in_process, args=(state_path, second_entered, release_second))

    first.start()
    try:
        assert first_entered.wait(10)
        second.start()
        assert not second_entered.wait(0.2)
        release_first.set()
        assert second_entered.wait(10)
        release_second.set()
        first.join(10)
        second.join(10)
        assert first.exitcode == 0
        assert second.exitcode == 0
    finally:
        release_first.set()
        release_second.set()
        for process in (first, second):
            if process.is_alive():
                process.terminate()
            process.join(10)

    assert read(state_path)["counter"] == 2


def test_workflow_state_error_is_an_automation_error() -> None:
    assert issubclass(WorkflowStateError, AutomationError)


@pytest.mark.parametrize("section", ["assets", "planning", "scene_phrases", "upload"])
def test_invalid_object_section_raises_typed_error_with_section(section: str) -> None:
    with pytest.raises(WorkflowStateSectionTypeError) as exc_info:
        WorkflowState({section: "invalid"})

    assert exc_info.value.section == section
    assert str(exc_info.value) == f"workflow-state.json::{section} must be an object"


def test_named_mutators_create_sections_and_use_canonical_updated_at() -> None:
    state = WorkflowState({"unknown": {"keep": True}})

    state.set_asset("music_prompts", True)
    state.set_planning("final_title", "Rainy Harbor")
    state.record_upload(video_id="video-123", video_url="https://youtu.be/video-123")
    state.record_master_video("01-master/video.mp4")

    document = state.to_dict()
    assert document["assets"] == {"music_prompts": True, "master_video": "01-master/video.mp4"}
    assert document["planning"] == {"final_title": "Rainy Harbor"}
    assert document["upload"] == {"video_id": "video-123", "video_url": "https://youtu.be/video-123"}
    assert document["unknown"] == {"keep": True}
    assert isinstance(document["updated_at"], str)
    assert datetime.strptime(document["updated_at"], "%Y-%m-%dT%H:%M:%S.%fZ").microsecond % 1000 == 0


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda state: state.set_asset("music_prompts", "yes"), "assets.music_prompts"),
        (lambda state: state.set_planning("generated", "yes"), "planning.generated"),
        (lambda state: state.record_master_video(True), "assets.master_video"),
    ],
)
def test_named_mutators_reject_invalid_known_values(mutator: Callable[[WorkflowState], None], message: str) -> None:
    state = WorkflowState({})

    with pytest.raises(WorkflowStateError, match=message):
        mutator(state)

    assert "updated_at" not in state


def test_record_upload_preserves_unsupplied_optional_fields() -> None:
    state = WorkflowState({"upload": {"video_id": "old", "video_url": "https://example.test/old", "future": "keep"}})

    state.record_upload(video_id="new")

    assert state.to_dict()["upload"] == {
        "video_id": "new",
        "video_url": "https://example.test/old",
        "future": "keep",
    }


class TestPlanningPlaylists:
    """#4346: planning.playlists は「未決定」と「auto_add のみ」を区別する。"""

    def _planning(self, tmp_path: Path, payload: object) -> object:
        state_path = tmp_path / "workflow-state.json"
        _write(state_path, {"planning": payload})
        state = read(state_path)
        assert state.planning is not None
        return state.planning

    def test_missing_key_reads_as_none(self, tmp_path: Path) -> None:
        assert self._planning(tmp_path, {"music": {"engine": "suno"}}).playlists is None

    def test_empty_array_is_preserved(self, tmp_path: Path) -> None:
        assert self._planning(tmp_path, {"playlists": []}).playlists == []

    def test_keys_are_returned_in_order(self, tmp_path: Path) -> None:
        assert self._planning(tmp_path, {"playlists": ["a", "b"]}).playlists == ["a", "b"]

    @pytest.mark.parametrize("payload", [None, "rain", {"key": "rain"}, [1], [""]])
    def test_invalid_shape_fails_loud(self, tmp_path: Path, payload: object) -> None:
        planning = self._planning(tmp_path, {"playlists": payload})
        with pytest.raises(WorkflowStateError, match="planning.playlists"):
            _ = planning.playlists

    def test_set_known_validates_shape(self, tmp_path: Path) -> None:
        planning = self._planning(tmp_path, {})
        planning.set_known("playlists", ["rain"])
        assert planning.playlists == ["rain"]
        with pytest.raises(WorkflowStateError, match="planning.playlists"):
            planning.set_known("playlists", "rain")
