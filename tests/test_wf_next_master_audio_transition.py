from __future__ import annotations

import json
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / ".claude" / "skills" / "wf-next" / "references" / "master_audio_transition.py"


def _collection(tmp_path: Path) -> Path:
    collection = tmp_path / "001-test-ambient-collection"
    (collection / "01-master").mkdir(parents=True)
    (collection / "01-master" / "raw-master.wav").write_bytes(b"raw")
    (collection / "workflow-state.json").write_text(
        json.dumps(
            {
                "phase": "prepared",
                "assets": {
                    "raw_master": "raw-master.wav",
                    "master_audio": None,
                },
            }
        ),
        encoding="utf-8",
    )
    return collection


def _run(
    collection: Path,
    *,
    skip_manual_mastering: bool,
    approval_gate_audio: bool,
    approved: str | None = None,
) -> subprocess.CompletedProcess[str]:
    args = [
        "python3",
        str(_SCRIPT),
        str(collection),
        "--skip-manual-mastering",
        str(skip_manual_mastering).lower(),
        "--approval-gate-audio",
        str(approval_gate_audio).lower(),
    ]
    if approved is not None:
        args.extend(["--approved", approved])
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _state(collection: Path) -> dict:
    return json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))


def test_raw_final_adopts_raw_master_when_skip_manual_mastering_is_true(tmp_path: Path) -> None:
    collection = _collection(tmp_path)

    result = _run(collection, skip_manual_mastering=True, approval_gate_audio=False)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "adopted"
    state = _state(collection)
    assert state["assets"]["master_audio"] == "raw-master.wav"
    assert state["phase"] == "mastered"


def test_raw_final_disabled_waits_without_state_update(tmp_path: Path) -> None:
    collection = _collection(tmp_path)

    result = _run(collection, skip_manual_mastering=False, approval_gate_audio=False)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "wait_for_master"
    state = _state(collection)
    assert state["assets"]["master_audio"] is None
    assert state["phase"] == "prepared"


def test_audio_gate_requests_approval_without_state_update(tmp_path: Path) -> None:
    collection = _collection(tmp_path)

    result = _run(collection, skip_manual_mastering=True, approval_gate_audio=True)

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["action"] == "needs_approval"
    assert output["master_audio"] == "raw-master.wav"
    state = _state(collection)
    assert state["assets"]["master_audio"] is None
    assert state["phase"] == "prepared"


def test_audio_gate_rejection_keeps_state_unchanged(tmp_path: Path) -> None:
    collection = _collection(tmp_path)

    result = _run(collection, skip_manual_mastering=True, approval_gate_audio=True, approved="no")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "approval_rejected"
    state = _state(collection)
    assert state["assets"]["master_audio"] is None
    assert state["phase"] == "prepared"


def test_audio_gate_approval_adopts_raw_master(tmp_path: Path) -> None:
    collection = _collection(tmp_path)

    result = _run(collection, skip_manual_mastering=True, approval_gate_audio=True, approved="yes")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "adopted"
    state = _state(collection)
    assert state["assets"]["master_audio"] == "raw-master.wav"
    assert state["phase"] == "mastered"
