"""Platform-neutral pull → agent → push sandwich execution."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from youtube_automation.application.media_handoff import HandoffSource, pull_handoff, push_handoff
from youtube_automation.core.errors import AutomationError, ResourceLimitError, StateSyncError, ValidationError
from youtube_automation.domains.cloud_planning import PlanningStagePolicy
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
from youtube_automation.domains.post_publish import PostPublishStagePolicy
from youtube_automation.infrastructure.auth.redaction import redact_sensitive_data
from youtube_automation.infrastructure.vcs.state_git import build_context
from youtube_automation.infrastructure.vcs.state_sync import (
    ChangeValidator,
    EventSink,
    default_change_validator,
    pull_update_commit_push,
)

Agent = Literal["claude", "codex"]
Stage = Literal["pipeline", "planning", "post-publish"]
AgentRunner = Callable[[Agent, str, Path], None]


class HybridResourceProbe(Protocol):
    def inspect(self) -> HybridResourceSnapshot: ...


HybridResourceEventSink = Callable[[NotificationEvent], None]
ResourceDiagnosticsSink = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class MediaHandoffRequest:
    collection_dir: str
    input_handoff: str | None = None
    input_destination: str | None = None
    output_handoff: str | None = None
    output_root: str | None = None
    output_files: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (self.input_handoff is None) != (self.input_destination is None):
            raise ValidationError("input handoff と destination は同時に指定してください")
        output_values = (self.output_handoff, self.output_root)
        if any(value is not None for value in output_values) != all(value is not None for value in output_values):
            raise ValidationError("output handoff と root は同時に指定してください")
        if self.output_handoff is None and self.output_files:
            raise ValidationError("output files には handoff と root が必要です")
        if self.output_handoff is not None and not self.output_files:
            raise ValidationError("output handoff には1件以上の file が必要です")
        for path_value in filter(
            None,
            (self.collection_dir, self.input_destination, self.output_root, *self.output_files),
        ):
            validate_media_relative_path("runner path", path_value)


@dataclass(frozen=True, slots=True)
class SandwichRequest:
    channel_dir: Path
    channel: str
    collection: str
    agent: Agent
    prompt: str
    commit_message: str
    stage: Stage = "pipeline"
    media_handoff: MediaHandoffRequest | None = None

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValidationError("sandwich runner prompt は空にできません")


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


class StagePolicy(Protocol):
    """Stage-specific execution semantics used by the sandwich pipeline."""

    @property
    def waiting(self) -> bool: ...

    @property
    def collection_name(self) -> str | None: ...

    def resolve(self) -> None: ...

    def prompt_for(self) -> str: ...

    def verify(self) -> str | None: ...

    def allows(self, repository: Path, changed: set[str]) -> None: ...


def _verify_input_reference(request: SandwichRequest, manifest: HandoffManifest) -> None:
    media = request.media_handoff
    if media is None or media.input_handoff is None:
        raise StateSyncError("input handoff policy is missing")
    state_path = _inside(request.channel_dir, media.collection_dir) / "workflow-state.json"
    handoff = read(state_path).handoff
    expected_key = f"{request.channel}/{request.collection}/{media.input_handoff}/{MANIFEST_NAME}"
    if (
        handoff is None
        or handoff.owner != "cloud"
        or handoff.manifest_key != expected_key
        or handoff.root_sha256 != manifest.root_sha256
    ):
        raise StateSyncError("workflow-state handoff参照とpull済みmanifestが一致しません")


@dataclass(slots=True)
class PipelineStagePolicy:
    """Media handoff and control-file policy for the default pipeline stage."""

    request: SandwichRequest
    store: MediaStore
    _validate: ChangeValidator | None = field(init=False, default=None, repr=False)

    @property
    def waiting(self) -> bool:
        return False

    @property
    def collection_name(self) -> str | None:
        return self.request.collection or None

    def resolve(self) -> None:
        # allowlistは既定validatorを唯一の定義として再利用し、fast-forward pull直後にsnapshotする。
        self._validate = default_change_validator(build_context(self.request.channel_dir))
        media = self.request.media_handoff
        if media is None or media.input_handoff is None or media.input_destination is None:
            return
        identity = HandoffIdentity(self.request.channel, self.request.collection, media.input_handoff)
        manifest = pull_handoff(
            self.store,
            identity,
            _inside(self.request.channel_dir, media.input_destination),
        )
        _verify_input_reference(self.request, manifest)

    def prompt_for(self) -> str:
        return self.request.prompt

    def verify(self) -> str | None:
        media = self.request.media_handoff
        if media is not None and media.output_handoff is not None and media.output_root is not None:
            root = _inside(self.request.channel_dir, media.output_root)
            sources = tuple(HandoffSource(_inside(root, path), path) for path in media.output_files)
            push_handoff(
                self.store,
                HandoffIdentity(
                    self.request.channel,
                    self.request.collection,
                    media.output_handoff,
                ),
                sources,
            )
        return self.request.collection or None

    def allows(self, repository: Path, changed: set[str]) -> None:
        if self._validate is None:
            raise StateSyncError("pipeline stage policyのresolveより先にallowsが呼ばれました")
        self._validate(repository, changed)


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


def _select_policy(request: SandwichRequest, store: MediaStore) -> StagePolicy:
    """The single stage-to-policy selection boundary."""
    if request.stage == "pipeline":
        return PipelineStagePolicy(request, store)
    if request.stage == "planning":
        return PlanningStagePolicy(request.channel_dir, request.prompt, request.media_handoff)
    return PostPublishStagePolicy(
        request.channel_dir, request.prompt, request.collection or None, request.media_handoff
    )


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
    # request と stage の整合検証は policy 構築時に起きるため、resource probe より前に選択する。
    policy = _select_policy(request, store)
    _guard_resources(request, resource_probe, on_resource_event, on_resource_diagnostics)
    context = build_context(request.channel_dir)
    result = SandwichResult("completed", request.collection or None)

    def writer() -> None:
        nonlocal result
        policy.resolve()
        if policy.waiting:
            result = SandwichResult("waiting", policy.collection_name)
            return
        agent_runner(request.agent, policy.prompt_for(), request.channel_dir)
        collection = policy.verify()
        result = SandwichResult("completed", collection)

    def validate_changes(repository: Path, changed: set[str]) -> None:
        if result.status == "waiting":
            if changed:
                raise StateSyncError("waiting cloud planning run must not change repository state")
            return
        policy.allows(repository, changed)

    pull_update_commit_push(
        context,
        writer,
        commit_message=request.commit_message,
        notification_channel=request.channel,
        notification_collection=request.collection,
        on_event=on_state_sync_event,
        change_validator=validate_changes,
    )
    return result
