"""Single owner for the review, selection, TOCTOU validation, and commit lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from youtube_automation.core.errors import ReviewError
from youtube_automation.domains.documents.review import (
    ReviewArtifact,
    ReviewCandidate,
    ReviewOutcome,
    ReviewSnapshot,
    ReviewTransport,
    SelectionManifest,
)
from youtube_automation.domains.documents.review_rendering import render_review_html, validate_review_html
from youtube_automation.infrastructure.browser import open_local_file
from youtube_automation.infrastructure.browser.selection_broker import SelectionBroker
from youtube_automation.infrastructure.documents.publishing import publish_html_snapshot


class ReviewSource(Protocol):
    """Adapter implemented by each reviewable artifact source."""

    @property
    def artifact(self) -> ReviewArtifact: ...

    @property
    def html_path(self) -> Path: ...

    def candidates(self) -> tuple[ReviewCandidate, ...]: ...

    def media(self) -> tuple[tuple[str, Path], ...]: ...

    def digest(self, candidates: tuple[ReviewCandidate, ...]) -> str: ...

    def commit(self, candidate: ReviewCandidate) -> None: ...


def review(
    source: ReviewSource,
    transport: ReviewTransport,
    automatic: bool,
    timeout: float,
    *,
    candidate_id: str | None = None,
) -> ReviewOutcome:
    """Select and commit a candidate only if the source remains unchanged."""
    snapshot = _snapshot(source)
    candidate_ids = tuple(candidate.id for candidate in snapshot.manifest.candidates)
    if not automatic and transport == "terminal" and candidate_id is None:
        return ReviewOutcome("terminal_required", snapshot.manifest.artifact_digest, candidate_ids)

    destination: Path | None = None
    if automatic:
        selected_id = snapshot.manifest.candidates[0].id
    elif transport == "terminal":
        selected_id = candidate_id
        if selected_id not in candidate_ids:
            raise ReviewError(f"候補IDがreview manifest allowlistにありません: {selected_id}")
    else:
        with SelectionBroker(snapshot.manifest) as broker:
            destination = _display(source.html_path, snapshot, broker.endpoint)
            selection = broker.wait(timeout=timeout)
        selected_id = selection.candidate_id
        if selection.artifact_digest != snapshot.manifest.artifact_digest:
            raise ReviewError("review中にartifactまたは候補実体が変わりました。未確定のまま再実行してください")

    current = _snapshot(source)
    selected = _same_selection(snapshot, current, selected_id)
    source.commit(selected)
    return ReviewOutcome(
        "selected",
        current.manifest.artifact_digest,
        candidate_ids,
        candidate_id=selected.id,
        html_path=destination,
    )


def preview(source: ReviewSource) -> ReviewOutcome:
    """Render one immutable source snapshot without committing a selection."""
    snapshot = _snapshot(source)
    destination = _display(source.html_path, snapshot, None)
    return ReviewOutcome(
        "displayed",
        snapshot.manifest.artifact_digest,
        tuple(candidate.id for candidate in snapshot.manifest.candidates),
        html_path=destination,
    )


def _snapshot(source: ReviewSource) -> ReviewSnapshot:
    candidates = source.candidates()
    manifest = SelectionManifest.create(
        artifact=source.artifact,
        artifact_digest=source.digest(candidates),
        candidates=candidates,
        now=datetime.now(UTC),
        lifetime=timedelta(minutes=5),
    )
    return ReviewSnapshot(manifest, source.media())


def _same_selection(original: ReviewSnapshot, current: ReviewSnapshot, candidate_id: str) -> ReviewCandidate:
    original_candidate = next((item for item in original.manifest.candidates if item.id == candidate_id), None)
    current_candidate = next((item for item in current.manifest.candidates if item.id == candidate_id), None)
    if (
        original.manifest.artifact_digest != current.manifest.artifact_digest
        or original_candidate is None
        or current_candidate is None
        or original_candidate.digest != current_candidate.digest
    ):
        raise ReviewError("review中にartifactまたは候補実体が変わりました。未確定のまま再実行してください")
    return current_candidate


def _display(destination: Path, snapshot: ReviewSnapshot, endpoint: str | None) -> Path:
    media = dict(snapshot.media)
    html = render_review_html(snapshot.manifest, endpoint=endpoint, media=media)
    publish_html_snapshot(
        destination,
        html,
        lambda persisted: validate_review_html(persisted, manifest=snapshot.manifest, endpoint=endpoint, media=media),
    )
    resolved = destination.resolve()
    if not open_local_file(resolved):
        raise ReviewError(f"browserでreview HTMLを開けません: {resolved}")
    return resolved


__all__ = ["ReviewSource", "preview", "review"]
