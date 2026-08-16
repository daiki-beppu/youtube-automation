"""Platform-neutral pull → agent → push sandwich execution."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from youtube_automation.application.media_handoff import HandoffSource, pull_handoff, push_handoff
from youtube_automation.core.errors import StateSyncError, ValidationError
from youtube_automation.domains.collections.workflow_state import read
from youtube_automation.domains.media_handoff_manifest import MANIFEST_NAME, HandoffIdentity, HandoffManifest
from youtube_automation.domains.media_store import MediaStore, validate_media_relative_path
from youtube_automation.infrastructure.auth.redaction import redact_sensitive_data
from youtube_automation.infrastructure.vcs.state_git import build_context
from youtube_automation.infrastructure.vcs.state_sync import pull_update_commit_push

Agent = Literal["claude", "codex"]
AgentRunner = Callable[[Agent, str, Path], None]


@dataclass(frozen=True, slots=True)
class SandwichRequest:
    channel_dir: Path
    collection_dir: str
    channel: str
    collection: str
    agent: Agent
    prompt: str
    commit_message: str
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


def run_sandwich(
    request: SandwichRequest,
    store: MediaStore,
    *,
    agent_runner: AgentRunner = run_agent,
) -> None:
    """Run the existing local-first workflow between verified MediaStore boundaries."""
    context = build_context(request.channel_dir)

    def writer() -> None:
        if request.input_handoff is not None and request.input_destination is not None:
            identity = HandoffIdentity(request.channel, request.collection, request.input_handoff)
            manifest = pull_handoff(store, identity, _inside(request.channel_dir, request.input_destination))
            _verify_input_reference(request, manifest)

        agent_runner(request.agent, request.prompt, request.channel_dir)

        if request.output_handoff is not None and request.output_root is not None:
            root = _inside(request.channel_dir, request.output_root)
            sources = tuple(HandoffSource(_inside(root, path), path) for path in request.output_files)
            push_handoff(store, HandoffIdentity(request.channel, request.collection, request.output_handoff), sources)

    pull_update_commit_push(context, writer, commit_message=request.commit_message)
