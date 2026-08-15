"""`/audit` の manifest と再開可能な状態判定を検証する。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.helpers.paths import REPO_ROOT
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.domains.skills.inventory import SkillInventory
from youtube_automation.infrastructure.documents.publishing import publish_json_document

INVENTORY = SkillInventory(REPO_ROOT)
SKILL_DIR = INVENTORY.skill_directory("audit")
SCRIPT = SKILL_DIR / "references" / "audit-chain-state.py"
MANIFEST = SKILL_DIR / "references" / "audit-chain-manifest.json"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("audit_chain_state", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def state() -> ModuleType:
    return _load_module()


def _write(path: Path, content: str = "{}\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _published_video(root: Path, *, collection: str = "collection-a", video_id: str = "video-123") -> None:
    _write(
        root / "collections" / "live" / collection / "workflow-state.json",
        json.dumps({"upload": {"video_id": video_id}}),
    )


def _completed_alignment(root: Path) -> None:
    _audit_pair(root / "docs" / "plans" / "alignment-audit.json", "alignment", "channel")


def _audit_pair(path: Path, audit_type: str, subject: str) -> None:
    _write(
        path,
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-08-16T00:00:00Z",
                "audit_type": audit_type,
                "subject": subject,
                "status": "PASS",
                "summary": "監査完了",
                "matrix": [{"check": "contract", "status": "PASS", "evidence": ["fixture"], "next_action": None}],
                "recommended_actions": [],
            }
        ),
    )
    publish_json_document(path, RepositorySchema.AUDIT_REPORT)


def _completed_video(root: Path, *, video_id: str = "video-123") -> None:
    _write(root / "data" / "video_analysis" / "channel" / f"{video_id}.json")
    _audit_pair(root / "reports" / "video_analysis" / "channel.json", "video", "channel")


def test_manifest_declares_four_read_only_steps_in_diagnostic_order() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["chainId"] == "audit"
    assert [step["id"] for step in manifest["steps"]] == ["alignment", "video", "metadata", "value-loop"]
    assert [step["skill"] for step in manifest["steps"]] == ["audit"] * 4
    assert all(step["approvalGate"]["skip"] is True for step in manifest["steps"])
    assert all("enabled" not in step["approvalGate"] for step in manifest["steps"])
    assert {step["idempotency"]["script"] for step in manifest["steps"]} == {"references/audit-chain-state.py"}


def test_flagless_audit_exposes_the_resumable_chain_contract() -> None:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = INVENTORY.frontmatter("audit")

    assert isinstance(frontmatter, dict)
    assert "フラグなしは4監査を状態判定付きで進め" in frontmatter["description"]
    assert "alignment → video → metadata → value-loop" in text
    assert "0 = `skip`" not in text
    for contract in ("| 0 | `skip` |", "| 10 | `run` |", "| 20 | `blocked` |"):
        assert contract in text
    assert "metadata / value-loop は診断結果を永続化しない" in text


def test_e6_keeps_only_the_intended_standalone_skills() -> None:
    skill_names = {path.name for path in INVENTORY.skill_directories()}

    e6_names = {
        "analytics",
        "alignment-check",
        "audit",
        "metadata-audit",
        "skill-feedback",
        "value-loop-audit",
        "video-analyze",
    }
    assert skill_names & e6_names == {"analytics", "audit", "skill-feedback"}


def test_alignment_runs_without_report_and_skips_after_report_is_saved(tmp_path: Path, state: ModuleType) -> None:
    run_code, runnable = state.evaluate(tmp_path, "alignment")
    _completed_alignment(tmp_path)
    skip_code, completed = state.evaluate(tmp_path, "alignment")

    assert (run_code, runnable["decision"], runnable["reason"]) == (
        state.EXIT_RUN,
        "run",
        "alignment_report_missing",
    )
    assert (skip_code, completed["decision"], completed["reason"]) == (
        state.EXIT_SKIP,
        "skip",
        "alignment_report_exists",
    )


@pytest.mark.parametrize("step", ["video", "metadata"])
def test_published_video_modes_block_with_reason_when_no_video_is_published(
    tmp_path: Path, state: ModuleType, step: str
) -> None:
    code, result = state.evaluate(tmp_path, step)

    assert code == state.EXIT_BLOCKED
    assert result["decision"] == "blocked"
    assert result["reason"] == "published_video_missing"


def test_video_runs_for_missing_analysis_and_skips_after_outputs_exist(tmp_path: Path, state: ModuleType) -> None:
    _published_video(tmp_path)

    run_code, runnable = state.evaluate(tmp_path, "video")
    _completed_video(tmp_path)
    skip_code, completed = state.evaluate(tmp_path, "video")

    assert (run_code, runnable["decision"], runnable["reason"]) == (
        state.EXIT_RUN,
        "run",
        "video_analysis_missing",
    )
    assert (skip_code, completed["decision"], completed["reason"]) == (
        state.EXIT_SKIP,
        "skip",
        "video_analysis_exists",
    )


def test_non_persistent_metadata_and_value_loop_remain_runnable(tmp_path: Path, state: ModuleType) -> None:
    _published_video(tmp_path)
    _completed_alignment(tmp_path)
    _completed_video(tmp_path)

    metadata_code, metadata = state.evaluate(tmp_path, "metadata")
    value_loop_code, value_loop = state.evaluate(tmp_path, "value-loop")

    assert (metadata_code, metadata["decision"], metadata["reason"]) == (
        state.EXIT_RUN,
        "run",
        "metadata_audit_is_not_persisted",
    )
    assert (value_loop_code, value_loop["decision"], value_loop["reason"]) == (
        state.EXIT_RUN,
        "run",
        "value_loop_audit_is_not_persisted",
    )


def test_value_loop_blocks_until_persisted_diagnostics_are_complete(tmp_path: Path, state: ModuleType) -> None:
    _published_video(tmp_path)

    alignment_code, alignment = state.evaluate(tmp_path, "value-loop")
    _completed_alignment(tmp_path)
    video_code, video = state.evaluate(tmp_path, "value-loop")

    assert (alignment_code, alignment["reason"]) == (state.EXIT_BLOCKED, "alignment_report_missing")
    assert (video_code, video["reason"]) == (state.EXIT_BLOCKED, "video_analysis_missing")


def test_restart_skips_persisted_steps_and_runs_non_persistent_steps(tmp_path: Path, state: ModuleType) -> None:
    _published_video(tmp_path)
    _completed_alignment(tmp_path)
    _completed_video(tmp_path)

    decisions = [state.evaluate(tmp_path, step) for step in state.STEPS]

    assert [(code, result["decision"]) for code, result in decisions] == [
        (state.EXIT_SKIP, "skip"),
        (state.EXIT_SKIP, "skip"),
        (state.EXIT_RUN, "run"),
        (state.EXIT_RUN, "run"),
    ]


def test_cli_reports_malformed_workflow_state_as_error(tmp_path: Path) -> None:
    _write(tmp_path / "collections" / "live" / "broken" / "workflow-state.json", "{broken")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--channel-dir", str(tmp_path), "--step", "video"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["decision"] == "error"
    assert "workflow-state.json" in payload["reason"]
