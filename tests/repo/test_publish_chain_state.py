"""State decisions for the initial ``/publish`` upload chain (#3841)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from tests.helpers.paths import REPO_ROOT

SCRIPT = REPO_ROOT / ".claude" / "skills" / "publish" / "references" / "publish-chain-state.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("publish_chain_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _collection(tmp_path: Path, upload: object) -> Path:
    collection = tmp_path / "collections" / "planning" / "sample"
    collection.mkdir(parents=True)
    (collection / "workflow-state.json").write_text(json.dumps({"upload": upload}), encoding="utf-8")
    return collection


def test_upload_runs_when_video_id_is_missing(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, {"video_id": None})

    code, result = module.evaluate(collection, "upload")

    assert code == module.EXIT_RUN
    assert result["decision"] == "run"
    assert result["reason"] == "video_id_missing"


def test_upload_skips_when_video_id_is_recorded(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, {"video_id": "youtube-id"})

    code, result = module.evaluate(collection, "upload")

    assert code == module.EXIT_SKIP
    assert result["decision"] == "skip"
    assert result["artifacts"] == ["workflow-state.json::upload.video_id"]


def test_upload_blocks_on_invalid_upload_state(tmp_path: Path) -> None:
    module = _module()
    collection = _collection(tmp_path, "invalid")

    code, result = module.evaluate(collection, "upload")

    assert code == module.EXIT_BLOCKED
    assert result["decision"] == "blocked"
    assert result["reason"] == "upload_state_invalid"
