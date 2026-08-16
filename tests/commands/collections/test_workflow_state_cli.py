"""``yt-workflow-state`` の制御面 CLI 契約。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.commands.collections import workflow_state_cli


def _collection(tmp_path: Path, state: dict[str, object] | None = None) -> Path:
    collection = tmp_path / "example-collection"
    (collection / "01-master").mkdir(parents=True)
    (collection / "02-Individual-music").mkdir()
    if state is not None:
        (collection / "workflow-state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return collection


def _read_state(collection: Path) -> dict[str, object]:
    return json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))


def test_get_outputs_json_value_and_missing_key_as_null(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    collection = _collection(tmp_path, {"upload": {"video_id": "video-123"}})

    assert workflow_state_cli.main(["--collection", str(collection), "get", "upload.video_id"]) == 0
    assert capsys.readouterr().out == '"video-123"\n'

    assert workflow_state_cli.main(["--collection", str(collection), "get", "upload.publish_at"]) == 0
    assert capsys.readouterr().out == "null\n"


def test_set_phase_uses_owner_update_and_preserves_unknown_fields(tmp_path: Path) -> None:
    collection = _collection(tmp_path, {"phase": "planning", "future": {"keep": True}})

    assert workflow_state_cli.main(["--collection", str(collection), "set-phase", "prepared"]) == 0

    state = _read_state(collection)
    assert isinstance(state.pop("updated_at"), str)
    assert state == {"phase": "prepared", "future": {"keep": True}}
    assert not list(collection.glob(".workflow-state.*.tmp"))


def test_invalid_phase_is_rejected_before_file_mutation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    collection = _collection(tmp_path, {"phase": "planning", "unknown": 1})
    state_path = collection / "workflow-state.json"
    before = state_path.read_bytes()

    with pytest.raises(SystemExit) as exc_info:
        workflow_state_cli.main(["--collection", str(collection), "set-phase", "invalid"])

    assert exc_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
    assert state_path.read_bytes() == before


def test_set_stage_supports_current_control_plane_vocabulary(tmp_path: Path) -> None:
    collection = _collection(tmp_path, {"stage": "planning"})

    assert workflow_state_cli.main(["--collection", str(collection), "set-stage", "live"]) == 0

    assert _read_state(collection)["stage"] == "live"


def test_set_upload_creates_section_and_only_overwrites_supplied_fields(tmp_path: Path) -> None:
    collection = _collection(
        tmp_path,
        {
            "upload": {
                "video_id": "old",
                "video_url": "https://example.test/old",
                "publish_at": "2026-08-16T00:00:00Z",
                "future": "keep",
            },
            "unknown": {"keep": True},
        },
    )

    assert workflow_state_cli.main(["--collection", str(collection), "set-upload", "--video-id", "new-video"]) == 0

    state = _read_state(collection)
    assert isinstance(state.pop("updated_at"), str)
    assert state == {
        "upload": {
            "video_id": "new-video",
            "video_url": "https://example.test/old",
            "publish_at": "2026-08-16T00:00:00Z",
            "future": "keep",
        },
        "unknown": {"keep": True},
    }

    fresh = _collection(tmp_path / "fresh")
    assert (
        workflow_state_cli.main(
            [
                "--collection",
                str(fresh),
                "set-upload",
                "--video-id",
                "video-456",
                "--video-url",
                "https://youtu.be/video-456",
                "--publish-at",
                "2026-08-17T00:00:00Z",
            ]
        )
        == 0
    )
    fresh_state = _read_state(fresh)
    assert isinstance(fresh_state["updated_at"], str)
    assert fresh_state["upload"] == {
        "video_id": "video-456",
        "video_url": "https://youtu.be/video-456",
        "publish_at": "2026-08-17T00:00:00Z",
    }


def test_collection_defaults_to_current_collection_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    collection = _collection(tmp_path, {"phase": "planning"})
    monkeypatch.chdir(collection)

    assert workflow_state_cli.main(["set-phase", "complete"]) == 0

    assert _read_state(collection)["phase"] == "complete"


def test_control_plane_updates_refresh_updated_at_and_touch_is_available(tmp_path: Path) -> None:
    collection = _collection(tmp_path, {"phase": "planning", "updated_at": "old", "unknown": True})

    assert workflow_state_cli.main(["--collection", str(collection), "set-phase", "prepared"]) == 0
    phase_updated_at = _read_state(collection)["updated_at"]
    assert isinstance(phase_updated_at, str)
    assert phase_updated_at != "old"

    assert workflow_state_cli.main(["--collection", str(collection), "touch"]) == 0
    state = _read_state(collection)
    assert isinstance(state["updated_at"], str)
    assert state["unknown"] is True


@pytest.mark.parametrize(
    ("command", "section", "key", "value"),
    [
        (("set-asset", "music_prompts", "true"), "assets", "music_prompts", True),
        (("set-asset", "master_video", '"01-master/video.mp4"'), "assets", "master_video", "01-master/video.mp4"),
        (("set-planning", "generated", "true"), "planning", "generated", True),
        (("set-planning", "final_title", '"Rainy Harbor"'), "planning", "final_title", "Rainy Harbor"),
        (
            ("set-planning", "music", '{"engine":"suno","mood":["mellow"]}'),
            "planning",
            "music",
            {"engine": "suno", "mood": ["mellow"]},
        ),
    ],
)
def test_typed_asset_and_planning_updates_preserve_unknown_fields(
    tmp_path: Path,
    command: tuple[str, ...],
    section: str,
    key: str,
    value: object,
) -> None:
    collection = _collection(tmp_path, {section: {"future": "keep"}, "unknown": {"keep": True}})

    assert workflow_state_cli.main(["--collection", str(collection), *command]) == 0

    state = _read_state(collection)
    assert isinstance(state.pop("updated_at"), str)
    assert state[section] == {"future": "keep", key: value}
    assert state["unknown"] == {"keep": True}


@pytest.mark.parametrize(
    "command",
    [
        ("set-asset", "music_prompts", '"yes"'),
        ("set-asset", "master_video", "true"),
        ("set-planning", "generated", '"yes"'),
        ("set-planning", "music", "[]"),
        ("set-planning", "music", '{"mood":"mellow"}'),
        ("set-post-upload-shorts", "{}"),
        ("set-post-upload-shorts", '[{"video_id":1}]'),
    ],
)
def test_typed_updates_reject_invalid_json_types_without_mutation(
    tmp_path: Path,
    command: tuple[str, ...],
) -> None:
    collection = _collection(tmp_path, {"unknown": {"keep": True}})
    state_path = collection / "workflow-state.json"
    before = state_path.read_bytes()

    assert workflow_state_cli.main(["--collection", str(collection), *command]) == 1

    assert state_path.read_bytes() == before


def test_legacy_completion_and_post_upload_sections_have_typed_commands(tmp_path: Path) -> None:
    collection = _collection(tmp_path, {"future": {"keep": True}})

    assert workflow_state_cli.main(["--collection", str(collection), "set-thumbnail-approved", "true"]) == 0
    assert workflow_state_cli.main(["--collection", str(collection), "set-description-generated", "true"]) == 0
    shorts = '[{"short_num":1,"video_id":"short-1","uploaded_at":"2026-08-16T00:00:00Z"}]'
    assert workflow_state_cli.main(["--collection", str(collection), "set-post-upload-shorts", shorts]) == 0

    state = _read_state(collection)
    assert state["assets"] == {"thumbnail": True, "description": True}
    assert "thumbnail" not in state
    assert "description" not in state
    assert state["post_upload"] == {
        "shorts": [{"short_num": 1, "video_id": "short-1", "uploaded_at": "2026-08-16T00:00:00Z"}]
    }
    assert state["future"] == {"keep": True}
