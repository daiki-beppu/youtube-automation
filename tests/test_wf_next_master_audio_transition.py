from __future__ import annotations

import json
import os
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
                "updated_at": "2000-01-01T00:00:00Z",
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
    approved_master_audio: str | None = None,
    selected_master_audio: str | None = None,
    main_repo_root: Path | None = None,
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
    if approved_master_audio is not None:
        args.extend(["--approved-master-audio", approved_master_audio])
    if selected_master_audio is not None:
        args.extend(["--selected-master-audio", selected_master_audio])
    env = None
    if main_repo_root is not None:
        env = os.environ.copy()
        env["WF_NEXT_MAIN_REPO_ROOT"] = str(main_repo_root)
    return subprocess.run(args, capture_output=True, text=True, check=False, env=env)


def _state(collection: Path) -> dict:
    return json.loads((collection / "workflow-state.json").read_text(encoding="utf-8"))


def _state_text(collection: Path) -> str:
    return (collection / "workflow-state.json").read_text(encoding="utf-8")


def _add_final_candidate(collection: Path, name: str = "final-master.wav") -> None:
    (collection / "01-master" / name).write_bytes(b"final")


def test_raw_final_adopts_raw_master_when_skip_manual_mastering_is_true(tmp_path: Path) -> None:
    collection = _collection(tmp_path)

    result = _run(collection, skip_manual_mastering=True, approval_gate_audio=False)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "adopted"
    state = _state(collection)
    assert state["assets"]["master_audio"] == "raw-master.wav"
    assert state["phase"] == "mastered"
    assert state["updated_at"] != "2000-01-01T00:00:00Z"
    assert state["updated_at"].endswith("Z")


def test_raw_final_disabled_waits_without_state_update(tmp_path: Path) -> None:
    collection = _collection(tmp_path)

    result = _run(collection, skip_manual_mastering=False, approval_gate_audio=False)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "wait_for_master"
    state = _state(collection)
    assert state["assets"]["master_audio"] is None
    assert state["phase"] == "prepared"
    assert state["updated_at"] == "2000-01-01T00:00:00Z"


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
    assert state["updated_at"] == "2000-01-01T00:00:00Z"


def test_audio_gate_rejection_keeps_state_unchanged(tmp_path: Path) -> None:
    collection = _collection(tmp_path)

    result = _run(
        collection,
        skip_manual_mastering=True,
        approval_gate_audio=True,
        approved="no",
        approved_master_audio="raw-master.wav",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "approval_rejected"
    state = _state(collection)
    assert state["assets"]["master_audio"] is None
    assert state["phase"] == "prepared"
    assert state["updated_at"] == "2000-01-01T00:00:00Z"


def test_audio_gate_approval_adopts_raw_master(tmp_path: Path) -> None:
    collection = _collection(tmp_path)

    result = _run(
        collection,
        skip_manual_mastering=True,
        approval_gate_audio=True,
        approved="yes",
        approved_master_audio="raw-master.wav",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "adopted"
    state = _state(collection)
    assert state["assets"]["master_audio"] == "raw-master.wav"
    assert state["phase"] == "mastered"
    assert state["updated_at"] != "2000-01-01T00:00:00Z"


def test_final_candidate_adopts_without_audio_gate(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    _add_final_candidate(collection)

    result = _run(collection, skip_manual_mastering=False, approval_gate_audio=False)

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["action"] == "adopted"
    assert output["master_audio"] == "final-master.wav"
    state = _state(collection)
    assert state["assets"]["master_audio"] == "final-master.wav"
    assert state["phase"] == "mastered"
    assert state["updated_at"] != "2000-01-01T00:00:00Z"


def test_final_candidate_audio_gate_requests_approval_without_state_update(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    _add_final_candidate(collection)

    result = _run(collection, skip_manual_mastering=False, approval_gate_audio=True)

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["action"] == "needs_approval"
    assert output["master_audio"] == "final-master.wav"
    state = _state(collection)
    assert state["assets"]["master_audio"] is None
    assert state["phase"] == "prepared"
    assert state["updated_at"] == "2000-01-01T00:00:00Z"


def test_final_candidate_audio_gate_rejection_keeps_state_unchanged(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    _add_final_candidate(collection)

    result = _run(
        collection,
        skip_manual_mastering=False,
        approval_gate_audio=True,
        approved="no",
        approved_master_audio="final-master.wav",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "approval_rejected"
    state = _state(collection)
    assert state["assets"]["master_audio"] is None
    assert state["phase"] == "prepared"
    assert state["updated_at"] == "2000-01-01T00:00:00Z"


def test_final_candidate_audio_gate_approval_adopts_selected_file(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    _add_final_candidate(collection)

    result = _run(
        collection,
        skip_manual_mastering=False,
        approval_gate_audio=True,
        approved="yes",
        approved_master_audio="final-master.wav",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "adopted"
    state = _state(collection)
    assert state["assets"]["master_audio"] == "final-master.wav"
    assert state["phase"] == "mastered"
    assert state["updated_at"] != "2000-01-01T00:00:00Z"


def test_multiple_final_candidates_need_selection_without_state_update(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    _add_final_candidate(collection, "final-a.wav")
    _add_final_candidate(collection, "final-b.wav")
    before = _state_text(collection)

    result = _run(collection, skip_manual_mastering=False, approval_gate_audio=False)

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["action"] == "needs_selection"
    assert output["candidates"] == ["final-a.wav", "final-b.wav"]
    assert _state_text(collection) == before


def test_selected_final_candidate_adopts_when_multiple_candidates_exist(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    _add_final_candidate(collection, "final-a.wav")
    _add_final_candidate(collection, "final-b.wav")

    result = _run(
        collection,
        skip_manual_mastering=False,
        approval_gate_audio=False,
        selected_master_audio="final-b.wav",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "adopted"
    state = _state(collection)
    assert state["assets"]["master_audio"] == "final-b.wav"
    assert state["phase"] == "mastered"


def test_selected_final_candidate_still_uses_audio_gate(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    _add_final_candidate(collection, "final-a.wav")
    _add_final_candidate(collection, "final-b.wav")

    result = _run(
        collection,
        skip_manual_mastering=False,
        approval_gate_audio=True,
        selected_master_audio="final-b.wav",
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["action"] == "needs_approval"
    assert output["master_audio"] == "final-b.wav"
    state = _state(collection)
    assert state["assets"]["master_audio"] is None
    assert state["phase"] == "prepared"


def test_audio_gate_approval_requires_approved_master_audio(tmp_path: Path) -> None:
    collection = _collection(tmp_path)

    result = _run(collection, skip_manual_mastering=True, approval_gate_audio=True, approved="yes")

    assert result.returncode == 1
    assert "approved-master-audio is required when --approved is set" in result.stderr
    state = _state(collection)
    assert state["assets"]["master_audio"] is None
    assert state["phase"] == "prepared"


def test_audio_gate_rechecks_approved_master_audio_before_adopting(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    _add_final_candidate(collection, "final-master.wav")

    result = _run(
        collection,
        skip_manual_mastering=False,
        approval_gate_audio=True,
        approved="yes",
        approved_master_audio="raw-master.wav",
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["action"] == "needs_approval"
    assert output["approved_master_audio"] == "raw-master.wav"
    assert output["master_audio"] == "final-master.wav"
    state = _state(collection)
    assert state["assets"]["master_audio"] is None
    assert state["phase"] == "prepared"


def test_main_repo_candidate_is_copied_to_worktree_before_state_update(tmp_path: Path) -> None:
    collection = _collection(tmp_path / "worktree")
    main_repo_root = tmp_path / "main"
    main_master_dir = main_repo_root / "collections" / "planning" / collection.name / "01-master"
    main_master_dir.mkdir(parents=True)
    (main_master_dir / "final-from-main.wav").write_bytes(b"main-final")

    result = _run(
        collection,
        skip_manual_mastering=False,
        approval_gate_audio=False,
        main_repo_root=main_repo_root,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "adopted"
    assert (collection / "01-master" / "final-from-main.wav").read_bytes() == b"main-final"
    state = _state(collection)
    assert state["assets"]["master_audio"] == "final-from-main.wav"
    assert state["phase"] == "mastered"


def test_worktree_and_main_repo_candidates_need_selection(tmp_path: Path) -> None:
    collection = _collection(tmp_path / "worktree")
    _add_final_candidate(collection, "worktree-final.wav")
    main_repo_root = tmp_path / "main"
    main_master_dir = main_repo_root / "collections" / "planning" / collection.name / "01-master"
    main_master_dir.mkdir(parents=True)
    (main_master_dir / "main-final.wav").write_bytes(b"main-final")
    before = _state_text(collection)

    result = _run(
        collection,
        skip_manual_mastering=False,
        approval_gate_audio=False,
        main_repo_root=main_repo_root,
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["action"] == "needs_selection"
    assert output["candidates"] == ["worktree-final.wav", "main-final.wav"]
    assert output["candidate_sources"] == [
        {"name": "worktree-final.wav", "source": "worktree"},
        {"name": "main-final.wav", "source": "main"},
    ]
    assert _state_text(collection) == before


def test_selected_main_repo_candidate_is_copied_to_worktree(tmp_path: Path) -> None:
    collection = _collection(tmp_path / "worktree")
    _add_final_candidate(collection, "worktree-final.wav")
    main_repo_root = tmp_path / "main"
    main_master_dir = main_repo_root / "collections" / "planning" / collection.name / "01-master"
    main_master_dir.mkdir(parents=True)
    (main_master_dir / "main-final.wav").write_bytes(b"main-final")

    result = _run(
        collection,
        skip_manual_mastering=False,
        approval_gate_audio=False,
        selected_master_audio="main-final.wav",
        main_repo_root=main_repo_root,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "adopted"
    assert (collection / "01-master" / "main-final.wav").read_bytes() == b"main-final"
    state = _state(collection)
    assert state["assets"]["master_audio"] == "main-final.wav"


def test_selected_raw_master_is_rejected_when_skip_manual_mastering_is_false(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    before = _state_text(collection)

    result = _run(
        collection,
        skip_manual_mastering=False,
        approval_gate_audio=False,
        selected_master_audio="raw-master.wav",
    )

    assert result.returncode == 1
    assert "selected-master-audio is not a final candidate: raw-master.wav" in result.stderr
    assert _state_text(collection) == before


def test_non_prepared_phase_is_noop_without_state_update(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    state = _state(collection)
    state["phase"] = "mastered"
    (collection / "workflow-state.json").write_text(json.dumps(state), encoding="utf-8")
    before = _state_text(collection)

    result = _run(collection, skip_manual_mastering=True, approval_gate_audio=False)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"action": "noop", "reason": "phase is not prepared"}
    assert _state_text(collection) == before


def test_raw_final_requires_raw_master_file_without_state_update(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    (collection / "01-master" / "raw-master.wav").unlink()
    before = _state_text(collection)

    result = _run(collection, skip_manual_mastering=True, approval_gate_audio=False)

    assert result.returncode == 1
    assert "master audio file does not exist: 01-master/raw-master.wav" in result.stderr
    assert _state_text(collection) == before


def test_invalid_json_fails_without_overwriting_state(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    state_path = collection / "workflow-state.json"
    state_path.write_text("{invalid", encoding="utf-8")

    result = _run(collection, skip_manual_mastering=True, approval_gate_audio=False)

    assert result.returncode == 1
    assert "invalid workflow-state.json" in result.stderr
    assert state_path.read_text(encoding="utf-8") == "{invalid"


def test_missing_workflow_state_fails_without_traceback(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    (collection / "workflow-state.json").unlink()

    result = _run(collection, skip_manual_mastering=True, approval_gate_audio=False)

    assert result.returncode == 1
    assert "workflow-state.json could not be read" in result.stderr
    assert "Traceback" not in result.stderr


def test_non_object_root_fails_without_overwriting_state(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    state_path = collection / "workflow-state.json"
    state_path.write_text("[]", encoding="utf-8")

    result = _run(collection, skip_manual_mastering=True, approval_gate_audio=False)

    assert result.returncode == 1
    assert "workflow-state.json root must be an object" in result.stderr
    assert state_path.read_text(encoding="utf-8") == "[]"


def test_non_object_assets_fails_without_overwriting_state(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    state_path = collection / "workflow-state.json"
    state_path.write_text(json.dumps({"phase": "prepared", "assets": []}), encoding="utf-8")
    before = state_path.read_text(encoding="utf-8")

    result = _run(collection, skip_manual_mastering=True, approval_gate_audio=False)

    assert result.returncode == 1
    assert "workflow-state.json::assets must be an object" in result.stderr
    assert state_path.read_text(encoding="utf-8") == before


def test_invalid_filename_fails_without_state_update(tmp_path: Path) -> None:
    collection = _collection(tmp_path)
    state = _state(collection)
    state["assets"]["raw_master"] = "../raw-master.wav"
    (collection / "workflow-state.json").write_text(json.dumps(state), encoding="utf-8")
    before = _state_text(collection)

    result = _run(collection, skip_manual_mastering=True, approval_gate_audio=False)

    assert result.returncode == 1
    assert "workflow-state.json::assets.raw_master must be a filename" in result.stderr
    assert _state_text(collection) == before
