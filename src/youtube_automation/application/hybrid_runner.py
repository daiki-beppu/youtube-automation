"""Platform-neutral pull → agent → push sandwich execution."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from youtube_automation.application.media_handoff import HandoffSource, pull_handoff, push_handoff
from youtube_automation.core.errors import AutomationError, ResourceLimitError, StateSyncError, ValidationError
from youtube_automation.domains.cloud_planning import (
    resolve_planning_readiness,
    validate_planning_changes,
    verify_planning_completion,
)
from youtube_automation.domains.collections.workflow_state import read
from youtube_automation.domains.hybrid_resource_guard import (
    HybridResourcePolicy,
    HybridResourceReport,
    HybridResourceSnapshot,
    evaluate_hybrid_resources,
)
from youtube_automation.domains.media_handoff_manifest import MANIFEST_NAME, HandoffIdentity, HandoffManifest
from youtube_automation.domains.media_store import MediaStore, validate_media_relative_path
from youtube_automation.domains.notifications import NotificationEvent, NotificationEventKind
from youtube_automation.domains.post_publish import (
    resolve_post_publish_readiness,
    validate_post_publish_changes,
    verify_post_publish_completion,
)
from youtube_automation.infrastructure.auth.redaction import redact_sensitive_data
from youtube_automation.infrastructure.vcs.state_git import build_context
from youtube_automation.infrastructure.vcs.state_sync import EventSink, pull_update_commit_push

Agent = Literal["claude", "codex"]
Stage = Literal["pipeline", "planning", "post-publish"]
AgentRunner = Callable[[Agent, str, Path], None]


class HybridResourceProbe(Protocol):
    def inspect(self) -> HybridResourceSnapshot: ...


HybridResourceEventSink = Callable[[NotificationEvent], None]
ResourceDiagnosticsSink = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class SandwichRequest:
    channel_dir: Path
    collection_dir: str
    channel: str
    collection: str
    agent: Agent
    prompt: str
    commit_message: str
    stage: Stage = "pipeline"
    input_handoff: str | None = None
    input_destination: str | None = None
    output_handoff: str | None = None
    output_root: str | None = None
    output_files: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValidationError("sandwich runner prompt は空にできません")
        if (self.input_handoff is None) != (self.input_destination is None):
            raise ValidationError("input handoff と destination は同時に指定してください")
        output_values = (self.output_handoff, self.output_root)
        if any(value is not None for value in output_values) != all(value is not None for value in output_values):
            raise ValidationError("output handoff と root は同時に指定してください")
        if self.output_handoff is None and self.output_files:
            raise ValidationError("output files には handoff と root が必要です")
        if self.output_handoff is not None and not self.output_files:
            raise ValidationError("output handoff には1件以上の file が必要です")
        if self.stage in {"planning", "post-publish"} and (
            self.input_handoff is not None or self.output_handoff is not None
        ):
            raise ValidationError(f"{self.stage} stage は media handoff を受け付けません")
        for field in filter(None, (self.collection_dir, self.input_destination, self.output_root, *self.output_files)):
            validate_media_relative_path("runner path", field)


def _inside(root: Path, relative: str) -> Path:
    path = root.joinpath(*relative.split("/"))
    current = root
    for segment in relative.split("/")[:-1]:
        current /= segment
        if current.is_symlink():
            raise ValidationError(f"sandwich runner path に symlink は使えません: {relative}")
    return path


def run_agent(agent: Agent, prompt: str, cwd: Path) -> None:
    """The only agent-process boundary; keep provider substitution here."""
    command = ["claude", "-p", prompt] if agent == "claude" else ["codex", "exec", prompt]
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        detail = redact_sensitive_data(completed.stderr.strip() or completed.stdout.strip())
        raise StateSyncError(f"agent CLI が失敗しました ({agent}, exit={completed.returncode}): {detail}")


@dataclass(frozen=True, slots=True)
class SandwichResult:
    status: Literal["completed", "waiting"]
    collection: str | None


def _verify_input_reference(request: SandwichRequest, manifest: HandoffManifest) -> None:
    state_path = _inside(request.channel_dir, request.collection_dir) / "workflow-state.json"
    handoff = read(state_path).handoff
    expected_key = f"{request.channel}/{request.collection}/{request.input_handoff}/{MANIFEST_NAME}"
    if (
        handoff is None
        or handoff.owner != "cloud"
        or handoff.manifest_key != expected_key
        or handoff.root_sha256 != manifest.root_sha256
    ):
        raise StateSyncError("workflow-state handoff参照とpull済みmanifestが一致しません")


def _resource_detail(report: HybridResourceReport) -> str:
    snapshot = report.snapshot
    policy = report.policy
    return (
        f"disk_free={snapshot.disk_free_bytes}/{policy.minimum_free_disk_bytes} bytes, "
        f"r2_retained={snapshot.r2_retained_bytes}/{policy.maximum_r2_retained_bytes} bytes, "
        f"generation_cost=${snapshot.generation_cost_usd}/${policy.maximum_generation_cost_usd}, "
        f"monthly_runs={snapshot.monthly_run_count + 1}, "
        f"projected_actions_minutes={report.projected_monthly_actions_minutes}/"
        f"{policy.maximum_monthly_actions_minutes}"
    )


def _guard_resources(
    request: SandwichRequest,
    resource_probe: HybridResourceProbe,
    on_event: HybridResourceEventSink | None,
    on_diagnostics: ResourceDiagnosticsSink | None,
) -> None:
    try:
        snapshot = resource_probe.inspect()
    except AutomationError as error:
        if on_event is not None:
            on_event(
                NotificationEvent(
                    NotificationEventKind.GUARD_EXCEEDED,
                    request.channel,
                    request.collection,
                    "resource-guard",
                    str(error),
                )
            )
        raise
    report = evaluate_hybrid_resources(snapshot, HybridResourcePolicy.zero_cost())
    detail = _resource_detail(report)
    if report.passed:
        if on_diagnostics is not None:
            on_diagnostics(detail)
        return
    rejection_detail = f"{detail}; " + "; ".join(issue.message for issue in report.issues)
    if on_event is not None:
        on_event(
            NotificationEvent(
                NotificationEventKind.GUARD_EXCEEDED,
                request.channel,
                request.collection,
                "resource-guard",
                rejection_detail,
            )
        )
    raise ResourceLimitError(f"hybrid resource guard rejected: {rejection_detail}")


def run_sandwich(
    request: SandwichRequest,
    store: MediaStore,
    *,
    resource_probe: HybridResourceProbe,
    agent_runner: AgentRunner = run_agent,
    on_resource_event: HybridResourceEventSink | None = None,
    on_resource_diagnostics: ResourceDiagnosticsSink | None = None,
    on_state_sync_event: EventSink | None = None,
) -> SandwichResult:
    """Run the existing local-first workflow between verified MediaStore boundaries."""
    _guard_resources(request, resource_probe, on_resource_event, on_resource_diagnostics)
    context = build_context(request.channel_dir)
    result = SandwichResult("completed", request.collection or None)
    planning_collection: Path | None = None
    post_publish_collection: Path | None = None

    def writer() -> None:
        nonlocal planning_collection, post_publish_collection, result
        if request.stage == "planning":
            readiness = resolve_planning_readiness(request.channel_dir)
            if readiness.status == "waiting":
                result = SandwichResult("waiting", readiness.collection.name if readiness.collection else None)
                return
            agent_runner(request.agent, request.prompt, request.channel_dir)
            planning_collection = verify_planning_completion(request.channel_dir, readiness.collection)
            result = SandwichResult("completed", planning_collection.name)
            return
        if request.stage == "post-publish":
            readiness = resolve_post_publish_readiness(request.channel_dir, request.collection or None)
            if readiness.status == "waiting":
                result = SandwichResult("waiting", None)
                return
            if readiness.collection is None:
                raise StateSyncError("cloud post-publish completion target is missing")
            targeted_prompt = (
                f"{request.prompt}\n"
                f"Cloud post-publish target is collection {readiness.collection.name!r}. "
                "Use the cloud executor and do not select or modify any other collection."
            )
            agent_runner(request.agent, targeted_prompt, request.channel_dir)
            post_publish_collection = verify_post_publish_completion(request.channel_dir, readiness.collection)
            result = SandwichResult("completed", post_publish_collection.name)
            return
        if request.input_handoff is not None and request.input_destination is not None:
            identity = HandoffIdentity(request.channel, request.collection, request.input_handoff)
            manifest = pull_handoff(store, identity, _inside(request.channel_dir, request.input_destination))
            _verify_input_reference(request, manifest)

        agent_runner(request.agent, request.prompt, request.channel_dir)

        if request.output_handoff is not None and request.output_root is not None:
            root = _inside(request.channel_dir, request.output_root)
            sources = tuple(HandoffSource(_inside(root, path), path) for path in request.output_files)
            push_handoff(store, HandoffIdentity(request.channel, request.collection, request.output_handoff), sources)

    def validate_changes(repository: Path, changed: set[str]) -> None:
        if result.status == "waiting":
            if changed:
                raise StateSyncError("waiting cloud planning run must not change repository state")
            return
        if request.stage == "planning":
            if planning_collection is None:
                raise StateSyncError("cloud planning completion target is missing")
            validate_planning_changes(repository, planning_collection, changed)
            return
        if post_publish_collection is None:
            raise StateSyncError("cloud post-publish completion target is missing")
        validate_post_publish_changes(repository, changed)

    pull_update_commit_push(
        context,
        writer,
        commit_message=request.commit_message,
        notification_channel=request.channel,
        notification_collection=request.collection,
        on_event=on_state_sync_event,
        change_validator=validate_changes if request.stage in {"planning", "post-publish"} else None,
    )
    return result
