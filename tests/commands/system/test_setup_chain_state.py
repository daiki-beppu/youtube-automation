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
from PIL import Image as PILImage

from tests.helpers.paths import REPO_ROOT
from youtube_automation.commands.system import doctor
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import publish_json_document

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
        if artifact == "branding/icon.*":
            path = root / "branding" / "icon.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            PILImage.new("RGB", (800, 800), color=(40, 80, 120)).save(path, format="PNG")
            continue
        if artifact == "branding/banner.*":
            path = root / "branding" / "banner.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            PILImage.new("RGB", (2048, 1152), color=(120, 80, 40)).save(path, format="PNG")
            continue
        if artifact == "docs/plans/viewer-voice-analysis.json":
            path = root / artifact
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "generated_at": "2026-08-16T00:00:00Z",
                        "report_type": "viewer_voice",
                        "summary": "voice",
                        "source_provenance": [
                            {"path": "data/comments.json", "collected_at": "2026-08-16", "claim": "voice"}
                        ],
                        "competitor_comparison": [],
                        "winning_patterns": [],
                        "evidence": [{"id": "ev-1", "source_path": "data/comments.json", "observation": "fact"}],
                        "application_candidates": [],
                    }
                ),
                encoding="utf-8",
            )
            publish_json_document(path, RepositorySchema.CHANNEL_RESEARCH_REPORT)
            continue
        if artifact == "docs/plans/viewer-voice-analysis.html" and (root / artifact).is_file():
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
    tool, channel = manifest["steps"][:2]
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
    tool, channel = manifest["steps"][:2]
    _write_file_artifacts(tmp_path, tool["outputArtifacts"] + channel["outputArtifacts"])
    _commit_workspace(tmp_path)
    (tmp_path / "config" / "channel" / "meta.json").write_text("changed\n", encoding="utf-8")

    code, result = state.evaluate(tmp_path, _checks(state), manifest, "channel")

    assert code == state.EXIT_RUN
    assert result["decision"] == "run"
    assert result["reason"] == "channel_outputs_incomplete"
    assert {item["artifact"] for item in result["artifacts"] if item["status"] != "ready"} == {"git:clean"}


def test_channel_does_not_inherit_clean_ancestor_repository(tmp_path: Path, state: ModuleType) -> None:
    manifest = state.load_manifest(MANIFEST)
    parent = tmp_path / "parent"
    channel_root = parent / "channel"
    parent.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=parent, check=True)
    (parent / ".gitignore").write_text("channel/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=parent, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Setup Test", "-c", "user.email=setup@example.invalid", "commit", "-qm", "parent"],
        cwd=parent,
        check=True,
    )
    tool, channel = manifest["steps"][:2]
    _write_file_artifacts(channel_root, tool["outputArtifacts"] + channel["outputArtifacts"])

    code, result = state.evaluate(channel_root, _checks(state), manifest, "channel")

    assert code == state.EXIT_RUN
    assert result["decision"] == "run"
    assert {item["artifact"]: item["status"] for item in result["artifacts"] if item["status"] != "ready"} == {
        "git:clean": "root_mismatch"
    }


def test_channel_does_not_treat_unborn_repository_as_saved(tmp_path: Path, state: ModuleType) -> None:
    manifest = state.load_manifest(MANIFEST)
    tool, channel = manifest["steps"][:2]
    _write_file_artifacts(tmp_path, tool["outputArtifacts"] + channel["outputArtifacts"])
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    code, result = state.evaluate(tmp_path, _checks(state), manifest, "channel")

    assert code == state.EXIT_RUN
    assert result["decision"] == "run"
    assert {item["artifact"]: item["status"] for item in result["artifacts"] if item["status"] != "ready"} == {
        "git:clean": "unborn"
    }


def test_channel_does_not_accept_nested_directory_inside_committed_repository(
    tmp_path: Path, state: ModuleType
) -> None:
    manifest = state.load_manifest(MANIFEST)
    repo = tmp_path / "repo"
    channel_root = repo / "nested-channel"
    tool, channel = manifest["steps"][:2]
    _write_file_artifacts(channel_root, tool["outputArtifacts"] + channel["outputArtifacts"])
    _commit_workspace(repo)

    code, result = state.evaluate(channel_root, _checks(state), manifest, "channel")

    assert code == state.EXIT_RUN
    assert result["decision"] == "run"
    assert {item["artifact"]: item["status"] for item in result["artifacts"] if item["status"] != "ready"} == {
        "git:clean": "root_mismatch"
    }


def test_channel_does_not_accept_ignored_setup_output_as_saved(tmp_path: Path, state: ModuleType) -> None:
    manifest = state.load_manifest(MANIFEST)
    tool, channel = manifest["steps"][:2]
    _write_file_artifacts(tmp_path, tool["outputArtifacts"] + channel["outputArtifacts"])
    ignored_output = "config/channel/meta.json"
    (tmp_path / ".gitignore").write_text(f"/{ignored_output}\n", encoding="utf-8")
    _commit_workspace(tmp_path)

    code, result = state.evaluate(tmp_path, _checks(state), manifest, "channel")

    assert code == state.EXIT_RUN
    assert result["decision"] == "run"
    assert {item["artifact"]: item["status"] for item in result["artifacts"] if item["status"] != "ready"} == {
        "git:clean": "unsaved"
    }


def test_channel_does_not_accept_untracked_file_after_initial_save(tmp_path: Path, state: ModuleType) -> None:
    manifest = state.load_manifest(MANIFEST)
    tool, channel = manifest["steps"][:2]
    _write_file_artifacts(tmp_path, tool["outputArtifacts"] + channel["outputArtifacts"])
    _commit_workspace(tmp_path)
    (tmp_path / "untracked.txt").write_text("not saved\n", encoding="utf-8")

    code, result = state.evaluate(tmp_path, _checks(state), manifest, "channel")

    assert code == state.EXIT_RUN
    assert result["decision"] == "run"
    assert {item["artifact"]: item["status"] for item in result["artifacts"] if item["status"] != "ready"} == {
        "git:clean": "dirty"
    }


@pytest.mark.parametrize("channel_config_status", ["fail", "warn"])
def test_channel_does_not_skip_when_channel_config_is_unresolved(
    tmp_path: Path, state: ModuleType, channel_config_status: str
) -> None:
    manifest = state.load_manifest(MANIFEST)
    tool, channel = manifest["steps"][:2]
    _write_file_artifacts(tmp_path, tool["outputArtifacts"] + channel["outputArtifacts"])
    _commit_workspace(tmp_path)

    code, result = state.evaluate(
        tmp_path,
        _checks(state, channel_config=channel_config_status),
        manifest,
        "channel",
    )

    assert (code, result["decision"], result["reason"]) == (
        state.EXIT_RUN,
        "run",
        "channel_outputs_incomplete",
    )
    assert {item["artifact"]: item["status"] for item in result["artifacts"] if item["status"] != "ready"} == {
        "doctor:channel_config": channel_config_status
    }


def test_channel_does_not_skip_when_channel_config_check_is_missing(tmp_path: Path, state: ModuleType) -> None:
    manifest = state.load_manifest(MANIFEST)
    tool, channel = manifest["steps"][:2]
    _write_file_artifacts(tmp_path, tool["outputArtifacts"] + channel["outputArtifacts"])
    _commit_workspace(tmp_path)
    checks = [check for check in _checks(state) if check.id != "channel_config"]

    code, result = state.evaluate(tmp_path, checks, manifest, "channel")

    assert code == state.EXIT_RUN
    assert result["decision"] == "run"
    assert {item["artifact"]: item["status"] for item in result["artifacts"] if item["status"] != "ready"} == {
        "doctor:channel_config": "missing"
    }


def test_present_but_invalid_channel_config_does_not_skip(tmp_path: Path, state: ModuleType) -> None:
    manifest = state.load_manifest(MANIFEST)
    tool, channel = manifest["steps"][:2]
    _write_file_artifacts(tmp_path, tool["outputArtifacts"] + channel["outputArtifacts"])
    (tmp_path / "config" / "channel" / "meta.json").write_text("not-json\n", encoding="utf-8")
    _commit_workspace(tmp_path)
    real_config_check = doctor.check_channel_config(tmp_path)
    checks = [check for check in _checks(state) if check.id != "channel_config"] + [real_config_check]

    code, result = state.evaluate(tmp_path, checks, manifest, "channel")

    assert real_config_check.status == "fail"
    assert code == state.EXIT_RUN
    assert result["decision"] == "run"
    assert {item["artifact"]: item["status"] for item in result["artifacts"] if item["status"] != "ready"} == {
        "doctor:channel_config": "fail"
    }


def _write_valid_branding(root: Path, *, banner_format: str = "PNG", banner_suffix: str = ".png") -> None:
    branding = root / "branding"
    branding.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (800, 800), color=(40, 80, 120)).save(branding / "icon.png", format="PNG")
    PILImage.new("RGB", (2048, 1152), color=(120, 80, 40)).save(
        branding / f"banner{banner_suffix}", format=banner_format
    )


@pytest.mark.parametrize(
    "kind",
    ["icon", "banner"],
)
@pytest.mark.parametrize(
    ("suffix", "mutation"),
    [
        (".txt", "text"),
        (".png", "empty"),
        (".png", "corrupt"),
        (".png", "directory"),
        (".png", "symlink"),
        (".png", "broken_symlink"),
        (".png.backup", "false_positive"),
        (".png", "wrong_ratio"),
        (".png", "oversize"),
        (".png", "format_mismatch"),
    ],
)
def test_channel_branding_glob_rejects_invalid_matches(
    tmp_path: Path, state: ModuleType, kind: str, suffix: str, mutation: str
) -> None:
    manifest = state.load_manifest(MANIFEST)
    tool, channel = manifest["steps"][:2]
    _write_file_artifacts(tmp_path, tool["outputArtifacts"] + channel["outputArtifacts"])
    valid = tmp_path / "branding" / f"{kind}.png"
    valid.unlink()
    invalid = tmp_path / "branding" / f"{kind}{suffix}"
    if mutation == "text":
        invalid.write_text("not an image\n", encoding="utf-8")
    elif mutation == "empty":
        invalid.write_bytes(b"")
    elif mutation in {"corrupt", "false_positive"}:
        invalid.write_bytes(b"\x89PNG\r\n\x1a\ntruncated")
    elif mutation == "directory":
        invalid.mkdir()
    elif mutation == "symlink":
        target = tmp_path / f"valid-{kind}.png"
        size = (800, 800) if kind == "icon" else (2048, 1152)
        PILImage.new("RGB", size, color=(40, 80, 120)).save(target, format="PNG")
        invalid.symlink_to(target)
    elif mutation == "broken_symlink":
        invalid.symlink_to(tmp_path / "missing-image.png")
    elif mutation == "wrong_ratio":
        PILImage.new("RGB", (800, 600), color=(40, 80, 120)).save(invalid, format="PNG")
    elif mutation == "oversize":
        size = (800, 800) if kind == "icon" else (2048, 1152)
        max_size = 4 * 1024 * 1024 if kind == "icon" else 6 * 1024 * 1024
        PILImage.new("RGB", size, color=(40, 80, 120)).save(invalid, format="PNG")
        with invalid.open("ab") as stream:
            stream.write(b"x" * max_size)
    elif mutation == "format_mismatch":
        size = (800, 800) if kind == "icon" else (2048, 1152)
        PILImage.new("RGB", size, color=(40, 80, 120)).save(invalid, format="JPEG")
    _commit_workspace(tmp_path)

    code, result = state.evaluate(tmp_path, _checks(state), manifest, "channel")

    assert code == state.EXIT_RUN
    assert result["decision"] == "run"
    statuses = {item["artifact"]: item["status"] for item in result["artifacts"]}
    assert statuses[f"branding/{kind}.*"] == "invalid"


@pytest.mark.parametrize(
    ("kind", "suffix", "image_format", "size"),
    [
        ("icon", ".jpg", "JPEG", (800, 800)),
        ("banner", ".webp", "WEBP", (2048, 1152)),
    ],
)
def test_channel_branding_glob_rejects_unsupported_valid_image_formats(
    tmp_path: Path,
    state: ModuleType,
    kind: str,
    suffix: str,
    image_format: str,
    size: tuple[int, int],
) -> None:
    manifest = state.load_manifest(MANIFEST)
    tool, channel = manifest["steps"][:2]
    _write_file_artifacts(tmp_path, tool["outputArtifacts"] + channel["outputArtifacts"])
    (tmp_path / "branding" / f"{kind}.png").unlink()
    PILImage.new("RGB", size, color=(40, 80, 120)).save(tmp_path / "branding" / f"{kind}{suffix}", format=image_format)
    _commit_workspace(tmp_path)

    code, result = state.evaluate(tmp_path, _checks(state), manifest, "channel")

    assert code == state.EXIT_RUN
    assert result["decision"] == "run"
    statuses = {item["artifact"]: item["status"] for item in result["artifacts"]}
    assert statuses[f"branding/{kind}.*"] == "invalid"


def test_channel_branding_globs_accept_valid_png_and_jpeg(tmp_path: Path, state: ModuleType) -> None:
    manifest = state.load_manifest(MANIFEST)
    tool, channel = manifest["steps"][:2]
    _write_file_artifacts(tmp_path, tool["outputArtifacts"] + channel["outputArtifacts"])
    (tmp_path / "branding" / "banner.png").unlink()
    _write_valid_branding(tmp_path, banner_format="JPEG", banner_suffix=".jpg")
    _commit_workspace(tmp_path)

    code, result = state.evaluate(tmp_path, _checks(state), manifest, "channel")

    assert code == state.EXIT_SKIP
    assert result["decision"] == "skip"
    branding = {
        item["artifact"]: item["status"] for item in result["artifacts"] if item["artifact"].startswith("branding/")
    }
    assert branding == {"branding/icon.*": "ready", "branding/banner.*": "ready"}


@pytest.mark.parametrize(
    ("kind", "size"),
    [
        ("icon", (799, 800)),
        ("icon", (801, 800)),
        ("banner", (1599, 900)),
        ("banner", (1601, 900)),
        ("banner", (1800, 1000)),
    ],
)
def test_channel_branding_rejects_near_ratio_misses(
    tmp_path: Path, state: ModuleType, kind: str, size: tuple[int, int]
) -> None:
    manifest = state.load_manifest(MANIFEST)
    tool, channel = manifest["steps"][:2]
    _write_file_artifacts(tmp_path, tool["outputArtifacts"] + channel["outputArtifacts"])
    PILImage.new("RGB", size, color=(40, 80, 120)).save(tmp_path / "branding" / f"{kind}.png", format="PNG")
    _commit_workspace(tmp_path)

    code, result = state.evaluate(tmp_path, _checks(state), manifest, "channel")

    assert code == state.EXIT_RUN
    assert result["decision"] == "run"
    statuses = {item["artifact"]: item["status"] for item in result["artifacts"]}
    assert statuses[f"branding/{kind}.*"] == "invalid"


@pytest.mark.parametrize(
    ("icon_size", "banner_size"),
    [
        ((64, 64), (16, 9)),
        ((800, 800), (2048, 1152)),
        ((1200, 1200), (2560, 1440)),
    ],
)
def test_channel_branding_accepts_exact_ratio_at_multiple_resolutions(
    tmp_path: Path,
    state: ModuleType,
    icon_size: tuple[int, int],
    banner_size: tuple[int, int],
) -> None:
    manifest = state.load_manifest(MANIFEST)
    tool, channel = manifest["steps"][:2]
    _write_file_artifacts(tmp_path, tool["outputArtifacts"] + channel["outputArtifacts"])
    PILImage.new("RGB", icon_size, color=(40, 80, 120)).save(tmp_path / "branding" / "icon.png", format="PNG")
    PILImage.new("RGB", banner_size, color=(120, 80, 40)).save(tmp_path / "branding" / "banner.png", format="PNG")
    _commit_workspace(tmp_path)

    code, result = state.evaluate(tmp_path, _checks(state), manifest, "channel")

    assert code == state.EXIT_SKIP
    assert result["decision"] == "skip"


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
