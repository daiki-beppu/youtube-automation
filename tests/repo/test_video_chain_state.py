"""State decisions for the resumable ``/video`` chain (#3835, #3836)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from tests.helpers.paths import REPO_ROOT
from tests.helpers.video_description import write_video_description_pair
from youtube_automation.application.master_video_review import VideoReviewPresentation, review_master_video

SCRIPT = REPO_ROOT / ".claude" / "skills" / "video" / "references" / "video-chain-state.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("video_chain_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _collection(tmp_path: Path, master_video: object) -> Path:
    collection = tmp_path / "collections" / "planning" / "sample"
    (collection / "01-master").mkdir(parents=True)
    (collection / "workflow-state.json").write_text(
        json.dumps({"assets": {"master_video": master_video}}),
        encoding="utf-8",
    )
    return collection


def test_generate_runs_when_master_video_is_not_recorded(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, None)

    code, result = module.evaluate(collection, "generate")

    assert code == module.EXIT_RUN
    assert result["decision"] == "run"
    assert result["reason"] == "master_video_missing"


def test_generate_blocks_when_recorded_master_video_is_empty(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, "01-master/sample-Master.mp4")
    (collection / "01-master" / "sample-Master.mp4").touch()

    code, result = module.evaluate(collection, "generate")

    assert code == module.EXIT_BLOCKED
    assert result["decision"] == "blocked"
    assert result["next"]


def test_generate_blocks_on_unsafe_recorded_master_video_path(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, "../outside.mp4")

    code, result = module.evaluate(collection, "generate")

    assert code == module.EXIT_BLOCKED
    assert result["decision"] == "blocked"
    assert result["reason"] == "master_video_path_invalid"


def test_describe_blocks_until_generated_master_video_exists(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, None)

    code, result = module.evaluate(collection, "describe")

    assert code == module.EXIT_BLOCKED
    assert result["decision"] == "blocked"
    assert result["reason"] == "master_video_missing"


def test_describe_runs_when_master_exists_and_description_is_incomplete(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, "01-master/master.mp4")
    (collection / "01-master" / "master.mp4").touch()

    code, result = module.evaluate(collection, "describe")

    assert code == module.EXIT_RUN
    assert result["decision"] == "run"
    assert result["reason"] == "description_incomplete"


def test_describe_skips_only_when_state_and_description_file_are_complete(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, "01-master/master.mp4")
    (collection / "01-master" / "master.mp4").touch()
    docs = collection / "20-documentation"
    docs.mkdir()
    write_video_description_pair(docs)
    state_path = collection / "workflow-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["assets"]["description"] = True
    state_path.write_text(json.dumps(state), encoding="utf-8")

    code, result = module.evaluate(collection, "describe")

    assert code == module.EXIT_SKIP
    assert result["decision"] == "skip"
    assert result["artifacts"] == [
        "20-documentation/descriptions.json",
        "20-documentation/descriptions.html",
    ]


def test_describe_does_not_skip_when_published_pair_is_tampered(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, "01-master/master.mp4")
    (collection / "01-master" / "master.mp4").touch()
    docs = collection / "20-documentation"
    docs.mkdir()
    source = write_video_description_pair(docs)
    source.with_suffix(".html").write_text("tampered", encoding="utf-8")
    state_path = collection / "workflow-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["assets"]["description"] = True
    state_path.write_text(json.dumps(state), encoding="utf-8")

    code, result = module.evaluate(collection, "describe")

    assert code == module.EXIT_RUN
    assert result["reason"] == "description_pair_invalid"


@pytest.mark.parametrize("damage", ["changed", "missing", "empty", "broken"])
def test_generate_resumes_only_current_approved_video(tmp_path: Path, damage: str) -> None:
    module = _module()
    collection = _collection(tmp_path, None)
    video = collection / "01-master/sample-Master.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=32x32:d=0.2", "-c:v", "libx264", str(video)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    state_path = collection / "workflow-state.json"
    state_path.write_text(json.dumps({"assets": {"master_audio": "sample.wav", "master_video": "sample-Master.mp4"}}))
    code, result = module.evaluate(collection, "generate")
    assert code == module.EXIT_BLOCKED
    assert result["next"]

    review_master_video(
        collection,
        kind="full",
        presentation=VideoReviewPresentation("static image", "none", "none", "completed"),
        automatic=True,
        transport="terminal",
        candidate_id=None,
        now=None,
        timeout=10,
    )
    before = state_path.read_bytes()
    for _ in range(2):
        code, result = module.evaluate(collection, "generate")
        assert code == module.EXIT_SKIP, result
        assert result["artifacts"] == ["01-master/sample-Master.mp4"]
    assert state_path.read_bytes() == before

    if damage == "changed":
        with video.open("ab") as stream:
            stream.write(b"changed after approval")
    elif damage == "missing":
        video.unlink()
    elif damage == "empty":
        video.write_bytes(b"")
    else:
        video.write_bytes(b"invalid video container")
    code, result = module.evaluate(collection, "generate")
    assert code == (module.EXIT_RUN if damage == "missing" else module.EXIT_BLOCKED)
    assert result["next"]
    assert state_path.read_bytes() == before
