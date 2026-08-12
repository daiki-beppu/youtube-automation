"""Deterministic setup chain state and fail-closed manifest contracts."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system import doctor

SCRIPT = REPO_ROOT / ".claude" / "skills" / "setup" / "references" / "setup-chain-state.py"
MANIFEST = REPO_ROOT / ".claude" / "skills" / "setup" / "references" / "setup-chain-manifest.json"


def _load_state() -> ModuleType:
    spec = importlib.util.spec_from_file_location("setup_chain_state_contract", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def state() -> ModuleType:
    return _load_state()


def _checks(state: ModuleType, **statuses: str) -> list[doctor.CheckResult]:
    check_ids = (*state.TOOL_CHECK_IDS, *state.CHANNEL_CHECK_IDS)
    return [
        doctor.CheckResult(id=check_id, status=statuses.get(check_id, "ok"), message=check_id) for check_id in check_ids
    ]


def _write_file_artifacts(root: Path, artifacts: list[str]) -> None:
    for artifact in artifacts:
        if artifact.startswith(("doctor:", "git:")):
            continue
        path = root / artifact.replace("*", "png")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ready\n", encoding="utf-8")


def _commit_workspace(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Setup Test", "-c", "user.email=setup@example.invalid", "commit", "-qm", "ready"],
        cwd=root,
        check=True,
    )


def test_channel_is_blocked_until_tool_prerequisites_are_complete(tmp_path: Path, state: ModuleType) -> None:
    manifest = state.load_manifest(MANIFEST)
    _write_file_artifacts(tmp_path, manifest["steps"][0]["outputArtifacts"])

    code, result = state.evaluate(tmp_path, _checks(state, oauth_token="warn"), manifest, "channel")

    assert (code, result["decision"], result["reason"]) == (
        state.EXIT_BLOCKED,
        "blocked",
        "tool_prerequisites_incomplete",
    )
    assert {artifact["artifact"] for artifact in result["artifacts"] if artifact["status"] != "ready"} == {
        "auth/token.json"
    }


def test_channel_runs_after_tool_and_skips_after_outputs_are_saved(tmp_path: Path, state: ModuleType) -> None:
    manifest = state.load_manifest(MANIFEST)
    tool, channel = manifest["steps"]
    _write_file_artifacts(tmp_path, tool["outputArtifacts"])
    checks = _checks(state)

    run_code, run_result = state.evaluate(tmp_path, checks, manifest, "channel")
    _write_file_artifacts(tmp_path, channel["outputArtifacts"])
    _commit_workspace(tmp_path)
    first_complete = state.evaluate(tmp_path, checks, manifest, "channel")
    second_complete = state.evaluate(tmp_path, checks, manifest, "channel")

    assert (run_code, run_result["decision"], run_result["reason"]) == (
        state.EXIT_RUN,
        "run",
        "channel_outputs_incomplete",
    )
    assert first_complete == second_complete
    assert first_complete[0] == state.EXIT_SKIP
    assert first_complete[1]["decision"] == "skip"
    assert first_complete[1]["reason"] == "channel_ready"


def test_channel_stays_run_when_initial_save_is_dirty(tmp_path: Path, state: ModuleType) -> None:
    manifest = state.load_manifest(MANIFEST)
    tool, channel = manifest["steps"]
    _write_file_artifacts(tmp_path, tool["outputArtifacts"] + channel["outputArtifacts"])
    _commit_workspace(tmp_path)
    (tmp_path / "config" / "channel" / "meta.json").write_text("changed\n", encoding="utf-8")

    code, result = state.evaluate(tmp_path, _checks(state), manifest, "channel")

    assert code == state.EXIT_RUN
    assert result["decision"] == "run"
    assert result["reason"] == "channel_outputs_incomplete"
    assert {item["artifact"] for item in result["artifacts"] if item["status"] != "ready"} == {"git:clean"}


def test_unrelated_informational_doctor_check_does_not_change_tool_decision(tmp_path: Path, state: ModuleType) -> None:
    manifest = state.load_manifest(MANIFEST)
    _write_file_artifacts(tmp_path, manifest["steps"][0]["outputArtifacts"])
    checks = _checks(state)
    checks.append(doctor.CheckResult(id="oauth_client_sharing", status="info", message="shared client available"))

    code, result = state.evaluate(tmp_path, checks, manifest, "tool")

    assert code == state.EXIT_SKIP
    assert result["decision"] == "skip"
    assert result["reason"] == "tool_ready"


def _write_manifest(tmp_path: Path, payload: dict[str, object]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "mutation",
    [
        "add_step",
        "remove_step",
        "reorder_steps",
        "duplicate_step",
        "unknown_step",
        "prerequisite_drift",
        "output_drift",
        "approval_not_skipped",
    ],
)
def test_manifest_mutations_fail_closed(tmp_path: Path, state: ModuleType, mutation: str) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    mutated = copy.deepcopy(manifest)
    steps = mutated["steps"]
    if mutation == "add_step":
        steps.append(copy.deepcopy(steps[-1]))
        steps[-1]["id"] = "extra"
    elif mutation == "remove_step":
        steps.pop()
    elif mutation == "reorder_steps":
        steps.reverse()
    elif mutation == "duplicate_step":
        steps[1]["id"] = "tool"
    elif mutation == "unknown_step":
        steps[1]["id"] = "research"
    elif mutation == "prerequisite_drift":
        steps[1]["prerequisiteArtifacts"] = steps[1]["prerequisiteArtifacts"][:-1]
    elif mutation == "output_drift":
        steps[1]["outputArtifacts"].append("docs/channel/unowned.md")
    elif mutation == "approval_not_skipped":
        steps[1]["approvalGate"]["skip"] = False

    with pytest.raises(state.ManifestError):
        state.load_manifest(_write_manifest(tmp_path, mutated))


def test_manifest_rejects_unknown_schema_and_mixed_approval_fields(tmp_path: Path, state: ModuleType) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    unknown = copy.deepcopy(manifest)
    unknown["steps"][0]["unexpected"] = True
    mixed = copy.deepcopy(manifest)
    mixed["steps"][0]["approvalGate"]["enabled"] = False

    with pytest.raises(state.ManifestError):
        state.load_manifest(_write_manifest(tmp_path / "unknown", unknown))
    with pytest.raises(state.ManifestError):
        state.load_manifest(_write_manifest(tmp_path / "mixed", mixed))


def test_invalid_manifest_cli_errors_before_doctor_execution(tmp_path: Path) -> None:
    invalid = _write_manifest(tmp_path, {"chainId": "setup", "steps": []})

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--channel-dir", str(tmp_path), "--manifest", str(invalid), "--step", "tool"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["decision"] == "error"
    assert payload["reason"].startswith("invalid manifest:")
    assert payload["artifacts"] == []
