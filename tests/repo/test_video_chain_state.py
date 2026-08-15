"""State decisions for the one-step ``/video`` chain (#3835)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from tests.helpers.paths import REPO_ROOT

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


def test_generate_skips_only_when_recorded_master_video_exists(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, "01-master/sample-Master.mp4")
    (collection / "01-master" / "sample-Master.mp4").touch()

    code, result = module.evaluate(collection, "generate")

    assert code == module.EXIT_SKIP
    assert result["decision"] == "skip"
    assert result["artifacts"] == ["01-master/sample-Master.mp4"]


def test_generate_blocks_on_unsafe_recorded_master_video_path(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, "../outside.mp4")

    code, result = module.evaluate(collection, "generate")

    assert code == module.EXIT_BLOCKED
    assert result["decision"] == "blocked"
    assert result["reason"] == "master_video_path_invalid"
