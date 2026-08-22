"""Safe preview/full master-video review through the shared lifecycle."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from youtube_automation.core.errors import ReviewError, ValidationError, WorkflowStateError
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.domains.collections.workflow_state import update as update_workflow_state
from youtube_automation.domains.documents.review import ReviewCandidate, SelectionManifest
from youtube_automation.domains.documents.review_rendering import render_review_html, validate_review_html
from youtube_automation.infrastructure.browser import open_local_file
from youtube_automation.infrastructure.browser.selection_broker import SelectionBroker
from youtube_automation.infrastructure.documents.publishing import publish_html_snapshot
from youtube_automation.infrastructure.media.probe import VideoProbe, probe_video

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


@dataclass(frozen=True)
class _VideoSnapshot:
    manifest: SelectionManifest
    path: Path
    probe: VideoProbe


def review_master_video(
    collection: Path,
    *,
    kind: VideoReviewKind,
    presentation: VideoReviewPresentation,
    automatic: bool,
    transport: ReviewTransport,
    candidate_id: str | None,
    now: datetime,
    timeout: float,
) -> MasterVideoReviewResult:
    """Review one fixed generated video and update state only for confirmed full output."""
    snapshot = _build_snapshot(collection, kind, presentation, now)
    allowed_id = snapshot.manifest.candidates[0].id
    destination: Path | None = None
    if automatic:
        selected_id = allowed_id
    elif transport == "terminal":
        if candidate_id is None:
            return MasterVideoReviewResult(
                "terminal_required",
                snapshot.manifest.artifact_digest,
                candidates=(allowed_id,),
            )
        selected_id = candidate_id
    else:
        if candidate_id is not None:
            raise ValidationError("candidate-idはterminal review専用です")
        with SelectionBroker(snapshot.manifest) as broker:
            destination = _display(collection, kind, snapshot, broker.endpoint)
            selection = broker.wait(timeout=timeout)
        current = _build_snapshot(collection, kind, presentation, now)
        if (
            selection.artifact_digest != snapshot.manifest.artifact_digest
            or current.manifest.artifact_digest != snapshot.manifest.artifact_digest
            or selection.candidate_id != allowed_id
        ):
            raise ReviewError("review中にmaster videoまたは表示条件が変わりました")
        selected_id = selection.candidate_id
    if selected_id != allowed_id:
        raise ValidationError(f"候補IDがreview manifest allowlistにありません: {selected_id}")
    current = _build_snapshot(collection, kind, presentation, now)
    if current.manifest.artifact_digest != snapshot.manifest.artifact_digest:
        raise ReviewError("master video確定前にartifact digestが変わりました")
    if kind == "full":
        _record_master_video(collection.resolve() / "workflow-state.json", current.path.name)
    return MasterVideoReviewResult(
        "selected",
        current.manifest.artifact_digest,
        selected_id,
        (allowed_id,),
        destination,
    )


def _build_snapshot(
    collection: Path,
    kind: VideoReviewKind,
    presentation: VideoReviewPresentation,
    now: datetime,
) -> _VideoSnapshot:
    root = _collection_root(collection)
    _require_pending_state(root)
    _validate_presentation(presentation)
    suffix = "Preview" if kind == "preview" else "Master"
    candidates = tuple(
        path.resolve()
        for path in (root / "01-master").glob(f"*-{suffix}.mp4")
        if path.is_file() and not path.is_symlink()
    )
    if len(candidates) != 1:
        raise ReviewError(f"{kind} master videoを一意に解決できません")
    path = candidates[0]
    probe = probe_video(path)
    if probe is None:
        raise ReviewError(f"ffprobeでmaster videoを検証できません: {path}")
    file_digest = _sha256(path)
    candidate_id = f"{kind}:{path.name}"
    detail_values = (
        kind,
        str(probe.duration_seconds),
        str(probe.width),
        str(probe.height),
        probe.codec,
        str(path.stat().st_size),
        presentation.background_route,
        presentation.effect,
        presentation.overlays,
        presentation.full_output_outlook,
    )
    candidate_digest = hashlib.sha256((file_digest + "\0" + "\0".join(detail_values)).encode()).hexdigest()
    label = f"preview（{probe.duration_seconds:.0f}秒短尺確認）" if kind == "preview" else "full master（完成動画）"
    candidate = ReviewCandidate(
        candidate_id,
        label,
        candidate_digest,
        details=(
            ("区分", label),
            ("ファイル名", path.name),
            ("duration", f"{probe.duration_seconds:.2f}秒"),
            ("resolution", f"{probe.width} × {probe.height}"),
            ("codec", probe.codec),
            ("filesize", f"{path.stat().st_size} bytes"),
            ("背景経路", presentation.background_route),
            ("effect", presentation.effect),
            ("overlay", presentation.overlays),
            ("Full output outlook", presentation.full_output_outlook),
        ),
    )
    artifact_digest = hashlib.sha256(f"{candidate_id}:{candidate_digest}".encode()).hexdigest()
    manifest = SelectionManifest.create(
        artifact="video",
        artifact_digest=artifact_digest,
        candidates=(candidate,),
        now=now,
        lifetime=timedelta(minutes=5),
    )
    return _VideoSnapshot(manifest, path, probe)


def _display(collection: Path, kind: VideoReviewKind, snapshot: _VideoSnapshot, endpoint: str) -> Path:
    destination = _collection_root(collection) / f"tmp/reviews/master-video-{kind}.html"
    media = {snapshot.manifest.candidates[0].id: snapshot.path}
    html = render_review_html(snapshot.manifest, endpoint=endpoint, media=media)
    publish_html_snapshot(
        destination,
        html,
        lambda persisted: validate_review_html(
            persisted,
            manifest=snapshot.manifest,
            endpoint=endpoint,
            media=media,
        ),
    )
    if not open_local_file(destination.resolve()):
        raise ReviewError(f"browserでmaster video review HTMLを開けません: {destination.resolve()}")
    return destination.resolve()


def _collection_root(collection: Path) -> Path:
    if collection.is_symlink() or not collection.is_dir():
        raise ReviewError(f"collection directoryが不正です: {collection}")
    master = collection / "01-master"
    if master.is_symlink() or not master.is_dir():
        raise ReviewError(f"01-master directoryが不正です: {master}")
    return collection.resolve()


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["MasterVideoReviewResult", "VideoReviewPresentation", "review_master_video"]
