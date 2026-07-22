"""Canonical wf-auto state resolver contracts after the automation-run migration."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".claude" / "skills" / "wf-auto" / "references" / "wf-auto-state.py"


def _load_state_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("wf_auto_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_collection(root: Path, name: str, created_at: str, *, phase: str = "planning") -> Path:
    collection = root / "collections" / "planning" / name
    collection.mkdir(parents=True)
    (collection / "workflow-state.json").write_text(
        json.dumps(
            {
                "created_at": created_at,
                "phase": phase,
                "stage": "planning",
                "music_engine": "lyria",
                "assets": {"raw_master": None},
                "upload": {"video_id": None},
                "planning": {"music": {"engine": "lyria"}},
            }
        ),
        encoding="utf-8",
    )
    return collection


def test_select_collection_returns_oldest_unfinished_planning_collection(tmp_path: Path) -> None:
    state = _load_state_module()
    newer = _write_collection(tmp_path, "newer", "2026-07-18T00:00:00Z")
    _write_collection(tmp_path, "older", "2026-07-17T00:00:00Z")

    assert state.select_collection(tmp_path) != newer
    assert state.select_collection(tmp_path).name == "older"


def test_prepared_collection_requires_audio_approval_when_not_skipped(tmp_path: Path) -> None:
    state = _load_state_module()
    collection = _write_collection(tmp_path, "prepared", "2026-07-18T00:00:00Z", phase="prepared")
    (collection / "01-master").mkdir()
    (collection / "01-master" / "raw.wav").write_bytes(b"raw")
    workflow = json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))
    workflow["assets"]["raw_master"] = "raw.wav"
    (collection / "workflow-state.json").write_text(json.dumps(workflow), encoding="utf-8")

    decision = state.evaluate_collection(
        tmp_path,
        collection,
        state.RunnerConfig(
            allow_external_publish=False,
            post_publish_configured=False,
            skip_audio_approval=False,
            skip_upload_approval=True,
        ),
    )

    assert decision["action"] == "blocked"
    assert decision["reason"] == "audio_approval_required"
