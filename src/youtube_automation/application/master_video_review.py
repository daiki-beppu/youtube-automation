"""Safe preview/full master-video review through the shared lifecycle."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from youtube_automation.application.review_lifecycle import ReviewSource, review, sha256_file
from youtube_automation.core.errors import ReviewError, ValidationError, WorkflowStateError
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.domains.collections.workflow_state import update as update_workflow_state
from youtube_automation.domains.documents.review import ReviewCandidate
from youtube_automation.infrastructure.browser import open_local_file
from youtube_automation.infrastructure.browser.selection_broker import SelectionBroker
from youtube_automation.infrastructure.media.probe import probe_video

VideoReviewKind = Literal["preview", "full"]
ReviewTransport = Literal["web", "terminal"]


@dataclass(frozen=True)
class VideoReviewPresentation:
    background_route: str
    effect: str
    overlays: str
    full_output_outlook: str


@dataclass(frozen=True)
class MasterVideoReviewResult:
    status: Literal["terminal_required", "selected"]
    artifact_digest: str
    candidate_id: str | None = None
    candidates: tuple[str, ...] = ()
    html_path: Path | None = None


class _VideoSource(ReviewSource):
    def __init__(self, collection: Path, kind: VideoReviewKind, presentation: VideoReviewPresentation) -> None:
        self.collection = collection
        self.kind = kind
        self.presentation = presentation
        self.path: Path | None = None

    @property
    def artifact(self):
        return "video"

    @property
    def html_path(self):
        # Review evidence belongs to the collection history.  Keeping it under
        # documentation (rather than tmp/) makes the exact preview/full page
        # available after the orchestrator run has ended.
        return self.collection.resolve() / f"20-documentation/reviews/master-video-{self.kind}.html"

    @property
    def compact_image_ids(self):
        return frozenset()

    def candidates(self):
        root = self.collection.resolve()
        _require_pending_state(root)
        _validate_presentation(self.presentation)
        suffix = "Preview" if self.kind == "preview" else "Master"
        paths = tuple(
            p.resolve() for p in (root / "01-master").glob(f"*-{suffix}.mp4") if p.is_file() and not p.is_symlink()
        )
        if len(paths) != 1:
            raise ReviewError(f"{self.kind} master videoを一意に解決できません")
        self.path = paths[0]
        probe = probe_video(self.path)
        if probe is None:
            raise ReviewError(f"ffprobeでmaster videoを検証できません: {self.path}")
        cid = f"{self.kind}:{self.path.name}"
        label = (
            f"preview（{probe.duration_seconds:.0f}秒短尺確認）"
            if self.kind == "preview"
            else "full master（完成動画）"
        )
        values = (
            self.kind,
            str(probe.duration_seconds),
            str(probe.width),
            str(probe.height),
            probe.codec,
            str(self.path.stat().st_size),
            self.presentation.background_route,
            self.presentation.effect,
            self.presentation.overlays,
            self.presentation.full_output_outlook,
        )
        digest = hashlib.sha256((sha256_file(self.path) + "\0" + "\0".join(values)).encode()).hexdigest()
        return (
            ReviewCandidate(
                cid,
                label,
                digest,
                (
                    ("区分", label),
                    ("ファイル名", self.path.name),
                    ("duration", f"{probe.duration_seconds:.2f}秒"),
                    ("resolution", f"{probe.width} × {probe.height}"),
                    ("codec", probe.codec),
                    ("filesize", f"{self.path.stat().st_size} bytes"),
                    ("背景経路", self.presentation.background_route),
                    ("effect", self.presentation.effect),
                    ("overlay", self.presentation.overlays),
                    ("Full output outlook", self.presentation.full_output_outlook),
                ),
            ),
        )

    def media(self):
        assert self.path is not None
        return ((f"{self.kind}:{self.path.name}", self.path),)

    def digest(self, candidates):
        return hashlib.sha256("\n".join(f"{c.id}:{c.digest}" for c in candidates).encode()).hexdigest()

    def commit(self, candidate):
        if self.kind == "full":
            _record_master_video(self.collection.resolve() / "workflow-state.json", candidate.id.split(":", 1)[1])


def review_master_video(
    collection: Path,
    *,
    kind: VideoReviewKind,
    presentation: VideoReviewPresentation,
    automatic: bool,
    transport: ReviewTransport,
    candidate_id: str | None,
    now,
    timeout: float,
) -> MasterVideoReviewResult:
    del now
    source = _VideoSource(collection, kind, presentation)
    outcome = review(
        source,
        transport,
        automatic,
        timeout,
        candidate_id=candidate_id,
        broker_factory=SelectionBroker,
        open_file=open_local_file,
    )
    return MasterVideoReviewResult(
        outcome.status, outcome.artifact_digest, outcome.candidate_id, outcome.candidates, outcome.html_path
    )


def _require_pending_state(collection: Path) -> None:
    try:
        state = read_workflow_state(collection / "workflow-state.json")
    except WorkflowStateError as error:
        raise ReviewError(f"workflow-state.jsonを読めません: {error}") from error
    if state.assets is None or state.assets.master_audio is None:
        raise ReviewError("master video reviewには確定済みmaster audioが必要です")


def _validate_presentation(presentation: VideoReviewPresentation) -> None:
    for label, value in (
        ("background-route", presentation.background_route),
        ("effect", presentation.effect),
        ("overlays", presentation.overlays),
        ("full-output-outlook", presentation.full_output_outlook),
    ):
        if not value.strip() or len(value) > 1024:
            raise ValidationError(f"{label}は1〜1024文字で指定してください")


def _record_master_video(state_path: Path, filename: str) -> None:
    def transition(state: WorkflowState) -> None:
        assets = state.assets
        if assets is None or assets.master_audio is None or assets.master_video is not None:
            raise WorkflowStateError("master video transition is no longer pending")
        state.record_master_video(filename)

    update_workflow_state(state_path, transition)


__all__ = ["MasterVideoReviewResult", "VideoReviewPresentation", "review_master_video"]
