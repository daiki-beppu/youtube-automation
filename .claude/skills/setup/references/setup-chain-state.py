#!/usr/bin/env python3
"""Return the deterministic resumable state of one setup chain step."""

from __future__ import annotations

import argparse
import json
import stat
import subprocess
import sys
from pathlib import Path
from typing import TypedDict, cast

from PIL import Image as PILImage
from PIL import UnidentifiedImageError

from youtube_automation.commands.system import doctor
from youtube_automation.core.errors import ConfigError, DocumentRenderError
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import read_published_json_document

EXIT_SKIP = 0
EXIT_RUN = 10
EXIT_BLOCKED = 20
EXIT_ERROR = 2
STEPS = ("tool", "channel")
MODE_ONLY_STEPS = ("import", "regenerate", "push")
TOOL_CHECK_IDS = (
    "ffmpeg",
    "ffprobe",
    "uv",
    "uv_project",
    "automation_package",
    "skills_synced",
    "gcloud",
    "gcloud_account",
    "gcp_project",
    "billing_linked",
    "apis_enabled",
    "adc",
    "adc_quota_project",
    "iam_aiplatform_user",
    "client_secrets",
    "oauth_token",
)
CHANNEL_CHECK_IDS = ("channel_config", "ttp_wf_new_readiness", "initial_setup_readiness")
TOOL_OUTPUT_ARTIFACTS = (
    *(f"doctor:{check_id}" for check_id in TOOL_CHECK_IDS[:-2]),
    "auth/client_secrets.json",
    "auth/token.json",
)
CHANNEL_OUTPUT_ARTIFACTS = (
    "config/channel/meta.json",
    "config/channel/content.json",
    "config/channel/youtube.json",
    "config/channel/analytics.json",
    "config/channel/playlists.json",
    "config/channel/workflow.json",
    "config/channel/audio.json",
    "config/localizations.json",
    "config/schedule_config.json",
    "config/skills/music.yaml",
    "config/skills/thumbnail.yaml",
    "doctor:channel_config",
    "docs/channel/ttp-seed-confirmation.md",
    "docs/channel/competitor-branding-snapshot.json",
    "docs/plans/viewer-voice-analysis.json",
    "docs/plans/viewer-voice-analysis.html",
    "docs/plans/viewing-scene-matrix.json",
    "docs/plans/viewing-scene-matrix.html",
    "docs/channel/personas/persona-definition.json",
    "docs/channel/personas/persona-definition.html",
    "branding/icon.*",
    "branding/banner.*",
    "doctor:ttp_wf_new_readiness",
    "doctor:initial_setup_readiness",
    "git:clean",
)
MODE_ONLY_CONTRACTS = {
    "import": (
        ("auth/client_secrets.json", "auth/token.json"),
        ("config/channel/meta.json", "doctor:channel_config", "auth/token.json"),
        "references/import-mode.md",
    ),
    "regenerate": (
        ("docs/channel/channel-direction.md",),
        ("config/channel/meta.json", "doctor:channel_config", "doctor:ttp_wf_new_readiness"),
        "references/regeneration-mode.md",
    ),
    "push": (
        ("auth/token.json", "config/channel/meta.json"),
        ("youtube:brandingSettings", "youtube:status", "youtube:localizations"),
        "references/push-mode.md",
    ),
}
_ALLOWED_CHECK_STATUSES = frozenset({"ok", "info", "warn", "fail", "unknown"})
_FILE_CHECK_IDS = {
    "auth/client_secrets.json": "client_secrets",
    "auth/token.json": "oauth_token",
}
_BRANDING_ARTIFACTS = {
    "branding/icon.*": ({".png": "PNG"}, (1, 1), 4 * 1024 * 1024),
    "branding/banner.*": ({".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}, (16, 9), 6 * 1024 * 1024),
}
_STEP_KEYS = frozenset(
    {
        "id",
        "skill",
        "defaultChain",
        "reference",
        "prerequisiteArtifacts",
        "outputArtifacts",
        "approvalGate",
        "idempotency",
    }
)


class ManifestError(ValueError):
    """The setup manifest cannot safely drive the chain."""


class SetupStep(TypedDict):
    id: str
    skill: str
    defaultChain: bool
    reference: str
    prerequisiteArtifacts: list[str]
    outputArtifacts: list[str]
    approvalGate: dict[str, object]
    idempotency: dict[str, str]


class SetupManifest(TypedDict):
    chainId: str
    steps: list[SetupStep]


class CheckPayload(TypedDict):
    id: str
    status: str


class ArtifactPayload(TypedDict):
    artifact: str
    status: str


class StateResult(TypedDict):
    step: str
    decision: str
    reason: str
    checks: list[CheckPayload]
    artifacts: list[ArtifactPayload]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def _approval_skip(gate: object) -> bool:
    _require(isinstance(gate, dict), "approvalGate must be an object")
    keys = set(gate)
    _require(keys in ({"skip", "configPath"}, {"enabled", "configPath"}), "approvalGate schema is invalid")
    if "skip" in gate:
        _require(isinstance(gate["skip"], bool), "approvalGate.skip must be boolean")
        return cast(bool, gate["skip"])
    _require(isinstance(gate["enabled"], bool), "approvalGate.enabled must be boolean")
    return not cast(bool, gate["enabled"])


def _validate_step(
    step: object,
    expected_id: str,
    prerequisites: tuple[str, ...],
    outputs: tuple[str, ...],
    *,
    default_chain: bool,
    reference: str,
) -> None:
    _require(isinstance(step, dict), "step must be an object")
    _require(set(step) == _STEP_KEYS, f"{expected_id} step schema is invalid")
    _require(step["id"] == expected_id, f"expected {expected_id} step")
    _require(step["skill"] == "setup", f"{expected_id} step skill must be setup")
    _require(step["defaultChain"] is default_chain, f"{expected_id} default chain membership drifted")
    _require(step["reference"] == reference, f"{expected_id} reference drifted")
    _require(step["prerequisiteArtifacts"] == list(prerequisites), f"{expected_id} prerequisites drifted")
    _require(step["outputArtifacts"] == list(outputs), f"{expected_id} outputs drifted")
    gate = step["approvalGate"]
    _require(_approval_skip(gate), f"{expected_id} approval gate must fail closed")
    _require(
        gate["configPath"] == f"workflow.setup.skip_approvals.{expected_id}",
        f"{expected_id} approval config path is invalid",
    )
    _require(
        step["idempotency"] == {"script": "references/setup-chain-state.py"},
        f"{expected_id} idempotency script is invalid",
    )


def load_manifest(path: Path) -> SetupManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ManifestError(str(exc)) from exc
    _require(isinstance(raw, dict) and set(raw) == {"chainId", "steps"}, "root schema is invalid")
    _require(raw["chainId"] == "setup", "chainId must be setup")
    steps = raw["steps"]
    _require(isinstance(steps, list), "steps must be an array")
    _require(
        [step.get("id") if isinstance(step, dict) else None for step in steps] == [*STEPS, *MODE_ONLY_STEPS],
        "steps must be tool, channel, import, regenerate, push",
    )
    _validate_step(steps[0], "tool", (), TOOL_OUTPUT_ARTIFACTS, default_chain=True, reference="references/tool.md")
    _validate_step(
        steps[1],
        "channel",
        TOOL_OUTPUT_ARTIFACTS,
        CHANNEL_OUTPUT_ARTIFACTS,
        default_chain=True,
        reference="references/channel-mode.md",
    )
    for step, expected_id in zip(steps[2:], MODE_ONLY_STEPS, strict=True):
        prerequisites, outputs, reference = MODE_ONLY_CONTRACTS[expected_id]
        _validate_step(
            step,
            expected_id,
            prerequisites,
            outputs,
            default_chain=False,
            reference=reference,
        )
    return cast(SetupManifest, raw)


def _check_map(checks: list[doctor.CheckResult]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for check in checks:
        if check.id in statuses:
            raise ValueError(f"duplicate doctor check: {check.id}")
        if check.status not in _ALLOWED_CHECK_STATUSES:
            raise ValueError(f"invalid doctor status for {check.id}: {check.status}")
        statuses[check.id] = check.status
    return statuses


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )


def _artifact_committed(root: Path, artifact: str) -> bool:
    if artifact.startswith(("doctor:", "git:")):
        return True
    if artifact in _BRANDING_ARTIFACTS:
        formats, ratio, max_size = _BRANDING_ARTIFACTS[artifact]
        candidates = [path for path in root.glob(artifact) if _valid_branding_image(path, formats, ratio, max_size)]
    else:
        candidates = [root / artifact]
    return any(
        _run_git(root, "cat-file", "-e", f"HEAD:{path.relative_to(root).as_posix()}").returncode == 0
        for path in candidates
    )


def _git_status(root: Path, artifacts: list[str]) -> str:
    top_level = _run_git(root, "rev-parse", "--show-toplevel")
    if top_level.returncode != 0:
        return "missing"
    if Path(top_level.stdout.strip()).resolve() != root:
        return "root_mismatch"
    if _run_git(root, "rev-parse", "--verify", "HEAD").returncode != 0:
        return "unborn"
    status = _run_git(root, "status", "--porcelain", "--untracked-files=all")
    if status.returncode != 0:
        return "missing"
    if status.stdout:
        return "dirty"
    if not all(_artifact_committed(root, artifact) for artifact in artifacts):
        return "unsaved"
    return "ready"


def _valid_branding_image(path: Path, formats: dict[str, str], ratio: tuple[int, int], max_size: int) -> bool:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_size == 0:
            return False
        if metadata.st_size > max_size:
            return False
        expected_format = formats.get(path.suffix.lower())
        if expected_format is None:
            return False
        with PILImage.open(path) as image:
            width, height = image.size
            actual_format = image.format
            image.verify()
    except (OSError, UnidentifiedImageError):
        return False
    if actual_format != expected_format or width <= 0 or height <= 0:
        return False
    ratio_width, ratio_height = ratio
    return width * ratio_height == height * ratio_width


def _branding_status(root: Path, artifact: str) -> str:
    formats, ratio, max_size = _BRANDING_ARTIFACTS[artifact]
    candidates = sorted(root.glob(artifact))
    if any(_valid_branding_image(path, formats, ratio, max_size) for path in candidates):
        return "ready"
    return "invalid" if candidates else "missing"


def _artifact_payload(root: Path, statuses: dict[str, str], artifacts: list[str]) -> list[ArtifactPayload]:
    payload: list[ArtifactPayload] = []
    for artifact in artifacts:
        if artifact.startswith("doctor:"):
            check_status = statuses.get(artifact.removeprefix("doctor:"), "missing")
            status = "ready" if check_status == "ok" else check_status
        elif artifact == "git:clean":
            status = _git_status(root, artifacts)
        elif artifact in _BRANDING_ARTIFACTS:
            status = _branding_status(root, artifact)
        elif artifact == "docs/plans/viewer-voice-analysis.json":
            path = root / artifact
            if not path.is_file() or not path.with_suffix(".html").is_file():
                status = "missing"
            else:
                try:
                    document = read_published_json_document(path, RepositorySchema.CHANNEL_RESEARCH_REPORT)
                    status = (
                        "ready"
                        if isinstance(document, dict) and document.get("report_type") == "viewer_voice"
                        else "invalid"
                    )
                except DocumentRenderError:
                    status = "invalid"
        else:
            exists = any(path.is_file() for path in root.glob(artifact))
            check_id = _FILE_CHECK_IDS.get(artifact)
            check_status = statuses.get(check_id, "missing") if check_id is not None else "ok"
            status = "ready" if exists and check_status == "ok" else check_status if exists else "missing"
        payload.append({"artifact": artifact, "status": status})
    return payload


def _result(
    step: str, decision: str, reason: str, checks: list[CheckPayload], artifacts: list[ArtifactPayload]
) -> StateResult:
    return {"step": step, "decision": decision, "reason": reason, "checks": checks, "artifacts": artifacts}


def evaluate(
    root: Path,
    checks: list[doctor.CheckResult],
    manifest: SetupManifest,
    step: str,
) -> tuple[int, StateResult]:
    if step not in STEPS:
        raise ValueError(f"unknown setup step: {step}")
    root = root.resolve()
    statuses = _check_map(checks)
    selected = next(item for item in manifest["steps"] if item["id"] == step)
    if step == "channel":
        prerequisites = _artifact_payload(root, statuses, selected["prerequisiteArtifacts"])
        if any(item["status"] != "ready" for item in prerequisites):
            return EXIT_BLOCKED, _result(step, "blocked", "tool_prerequisites_incomplete", [], prerequisites)

    artifacts = _artifact_payload(root, statuses, selected["outputArtifacts"])
    incomplete = [item for item in artifacts if item["status"] != "ready"]
    if incomplete:
        if step == "tool":
            checks_payload = [
                {"id": item["artifact"].removeprefix("doctor:"), "status": item["status"]}
                for item in incomplete
                if item["artifact"].startswith("doctor:")
            ]
            return EXIT_RUN, _result(step, "run", "tool_checks_unresolved", checks_payload, artifacts)
        return EXIT_RUN, _result(step, "run", "channel_outputs_incomplete", [], artifacts)

    stale = [check for check in checks if check.id == "analytics_report" and check.status == "fail"]
    if step == "tool" and len(stale) == 1:
        return EXIT_SKIP, _result(
            step,
            "skip",
            "tool_ready_analytics_report_stale",
            [{"id": "analytics_report", "status": "fail"}],
            artifacts,
        )
    reason = "tool_ready" if step == "tool" else "channel_ready"
    return EXIT_SKIP, _result(step, "skip", reason, [], artifacts)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-dir", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("setup-chain-manifest.json"))
    parser.add_argument("--step", choices=STEPS, required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.channel_dir.resolve()
    try:
        manifest = load_manifest(args.manifest.resolve())
        code, result = evaluate(root, doctor.run_all_checks(root), manifest, args.step)
    except ManifestError as exc:
        code = EXIT_ERROR
        result = _result(args.step, "error", f"invalid manifest: {exc}", [], [])
    except (ConfigError, OSError, ValueError) as exc:
        code = EXIT_ERROR
        result = _result(args.step, "error", str(exc), [], [])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
