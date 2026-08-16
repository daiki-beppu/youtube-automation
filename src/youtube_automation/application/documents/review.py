"""Read-only review display and product-neutral selection orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from youtube_automation.application.documents.collection_plan import (
    collection_plan_artifact_digest,
    collection_plan_candidate_digest,
)
from youtube_automation.core.errors import ReviewError
from youtube_automation.domains.documents.review import ReviewArtifact, ReviewCandidate, SelectionManifest
from youtube_automation.domains.documents.review_rendering import render_review_html, validate_review_html
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.browser import open_local_file
from youtube_automation.infrastructure.browser.selection_broker import SelectionBroker
from youtube_automation.infrastructure.documents.publishing import publish_html_snapshot, read_published_json_document

ReviewTransport = Literal["web", "terminal"]
ReviewStatus = Literal["skipped", "displayed", "terminal_required", "selected"]
_MEDIA_SUFFIXES = {
    "thumbnail": frozenset({".jpg", ".jpeg", ".png", ".webp"}),
    "audio": frozenset({".mp3", ".wav", ".flac", ".m4a"}),
    "video": frozenset({".mp4", ".mov", ".webm"}),
}


@dataclass(frozen=True)
class ReviewResult:
    status: ReviewStatus
    artifact_digest: str | None = None
    candidate_id: str | None = None
    candidates: tuple[str, ...] = ()
    html_path: Path | None = None


@dataclass(frozen=True)
class _ReviewSnapshot:
    manifest: SelectionManifest
    media: tuple[tuple[str, Path], ...]
    persistent_html: Path | None

    def media_mapping(self) -> dict[str, Path]:
        return dict(self.media)


def run_review(
    collection_dir: Path,
    artifact: ReviewArtifact,
    *,
    automatic: bool = False,
    selection: bool = False,
    transport: ReviewTransport = "web",
    timeout: float = 300,
    now: datetime | None = None,
) -> ReviewResult:
    """Display a fixed review page and optionally return one validated candidate ID.

    This function never mutates a canonical artifact or workflow state. Callers own
    all approval semantics and state transitions after revalidating the result.
    """
    if automatic:
        return ReviewResult(status="skipped")
    instant = now or datetime.now(UTC)
    resolved_collection = _resolve_collection(collection_dir)
    snapshot = _build_snapshot(resolved_collection, artifact, now=instant)
    candidate_ids = tuple(candidate.id for candidate in snapshot.manifest.candidates)
    if transport == "terminal":
        return ReviewResult(
            status="terminal_required",
            artifact_digest=snapshot.manifest.artifact_digest,
            candidates=candidate_ids,
        )
    if not selection:
        destination = _display_snapshot(resolved_collection, artifact, snapshot, endpoint=None)
        return ReviewResult(
            status="displayed", artifact_digest=snapshot.manifest.artifact_digest, html_path=destination
        )

    with SelectionBroker(snapshot.manifest) as broker:
        destination = _display_snapshot(resolved_collection, artifact, snapshot, endpoint=broker.endpoint)
        broker_selection = broker.wait(timeout=timeout)
    current = _build_snapshot(resolved_collection, artifact, now=instant)
    if current.manifest.artifact_digest != broker_selection.artifact_digest:
        raise ReviewError("review中にartifact digestが変わりました。未選択のまま再実行してください")
    current_candidate = next(
        (candidate for candidate in current.manifest.candidates if candidate.id == broker_selection.candidate_id), None
    )
    original_candidate = next(
        (candidate for candidate in snapshot.manifest.candidates if candidate.id == broker_selection.candidate_id), None
    )
    if current_candidate is None or original_candidate is None or current_candidate.digest != original_candidate.digest:
        raise ReviewError("review中に候補実体が変わりました。未選択のまま再実行してください")
    return ReviewResult(
        status="selected",
        artifact_digest=current.manifest.artifact_digest,
        candidate_id=current_candidate.id,
        candidates=candidate_ids,
        html_path=destination,
    )


def _display_snapshot(
    collection_dir: Path,
    artifact: ReviewArtifact,
    snapshot: _ReviewSnapshot,
    *,
    endpoint: str | None,
) -> Path:
    if snapshot.persistent_html is not None and not open_local_file(snapshot.persistent_html):
        raise ReviewError(f"browserで永続review HTMLを開けません: {snapshot.persistent_html.resolve()}")
    if snapshot.persistent_html is not None and endpoint is None:
        return snapshot.persistent_html.resolve()
    suffix = "-selection" if snapshot.persistent_html is not None else ""
    destination = collection_dir / "tmp" / "reviews" / f"{artifact}{suffix}.html"
    media = snapshot.media_mapping()
    html = render_review_html(snapshot.manifest, endpoint=endpoint, media=media)
    publish_html_snapshot(
        destination,
        html,
        lambda persisted: validate_review_html(persisted, manifest=snapshot.manifest, endpoint=endpoint, media=media),
    )
    if not open_local_file(destination.resolve()):
        raise ReviewError(f"browserでreview HTMLを開けません: {destination.resolve()}")
    return destination.resolve()


def _build_snapshot(collection_dir: Path, artifact: ReviewArtifact, *, now: datetime) -> _ReviewSnapshot:
    persistent_html: Path | None = None
    media: tuple[tuple[str, Path], ...] = ()
    if artifact == "plan":
        source = collection_dir / "20-documentation" / "plan_proposals.json"
        document = read_published_json_document(source, RepositorySchema.COLLECTION_PLAN)
        candidates = _plan_candidates(source, document)
        media = _plan_media(collection_dir, document)
        persistent_html = source.with_suffix(".html").resolve()
        artifact_digest = collection_plan_artifact_digest(source)
    elif artifact == "music-prompt":
        sources = [
            path
            for name in ("suno-prompts.json", "lyria-prompt.json")
            if (path := collection_dir / "20-documentation" / name).is_file()
        ]
        if len(sources) != 1:
            raise ReviewError("music promptの永続JSON+HTML pairを一意に解決できません")
        source = sources[0]
        read_published_json_document(source, RepositorySchema.MUSIC_PROMPT)
        artifact_digest = _sha256_file(source)
        candidates = (
            ReviewCandidate("approve", "承認", artifact_digest),
            ReviewCandidate("reject", "差し戻し", artifact_digest),
        )
        persistent_html = source.with_suffix(".html").resolve()
    else:
        paths = _media_candidates(collection_dir, artifact)
        media = tuple((f"candidate-{index}", path) for index, path in enumerate(paths, 1))
        candidates = tuple(ReviewCandidate(candidate_id, path.name, _sha256_file(path)) for candidate_id, path in media)
        artifact_digest = _candidate_set_digest(candidates)
    manifest = SelectionManifest.create(
        artifact=artifact,
        artifact_digest=artifact_digest,
        candidates=candidates,
        now=now,
        lifetime=timedelta(minutes=5),
    )
    return _ReviewSnapshot(manifest=manifest, media=media, persistent_html=persistent_html)


def _resolve_collection(collection_dir: Path) -> Path:
    if collection_dir.is_symlink() or not collection_dir.is_dir():
        raise ReviewError(f"collection directoryが不正です: {collection_dir}")
    return collection_dir.resolve()


def _media_candidates(collection_dir: Path, artifact: ReviewArtifact) -> tuple[Path, ...]:
    suffixes = _MEDIA_SUFFIXES[artifact]
    roots = (
        (collection_dir / "10-assets",)
        if artifact == "thumbnail"
        else (collection_dir / "01-master",)
        if artifact == "audio"
        else (collection_dir / "10-assets", collection_dir / "01-master")
    )
    paths = tuple(
        sorted(
            path.resolve()
            for root in roots
            if root.is_dir() and not root.is_symlink()
            for path in root.iterdir()
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in suffixes
        )
    )
    if not paths:
        raise ReviewError(f"review候補がありません: {artifact}")
    if len({path.name for path in paths}) != len(paths):
        raise ReviewError(f"review候補のfilenameが重複しています: {artifact}")
    return paths


def _plan_candidates(source: Path, document: object) -> tuple[ReviewCandidate, ...]:
    if not isinstance(document, dict) or not isinstance(document.get("candidates"), list):
        raise ReviewError("collection plan candidatesを解決できません")
    result: list[ReviewCandidate] = []
    for item in document["candidates"]:
        if not isinstance(item, dict) or not isinstance(item.get("plan_id"), str):
            raise ReviewError("collection plan candidate IDが不正です")
        label = item.get("final_title")
        result.append(
            ReviewCandidate(
                item["plan_id"],
                label if isinstance(label, str) else item["plan_id"],
                collection_plan_candidate_digest(source, item),
                details=_plan_details(item),
            )
        )
    return tuple(result)


def _plan_details(candidate: dict[str, object]) -> tuple[tuple[str, str], ...]:
    evidence = candidate.get("evidence")
    constraints = candidate.get("constraint_compliance")
    return (
        ("対象視聴者", _display_text(candidate.get("target_persona"))),
        ("視聴シーン", _display_text(candidate.get("viewing_scene"))),
        ("音楽方針", _display_text(candidate.get("music_direction"))),
        ("映像方針", _display_text(candidate.get("video_direction"))),
        ("サムネ方針", _display_text(candidate.get("thumbnail_direction"))),
        ("根拠", _list_summary(evidence, "observation")),
        ("制約適合", _list_summary(constraints, "constraint_id")),
    )


def _plan_media(collection_dir: Path, document: object) -> tuple[tuple[str, Path], ...]:
    if not isinstance(document, dict) or not isinstance(document.get("candidates"), list):
        raise ReviewError("collection plan candidatesを解決できません")
    root = collection_dir.resolve()
    result: list[tuple[str, Path]] = []
    for candidate in document["candidates"]:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("plan_id"), str):
            raise ReviewError("collection plan candidate IDが不正です")
        assets = candidate.get("preview_assets")
        if not isinstance(assets, list):
            raise ReviewError("collection plan preview_assetsが不正です")
        if not assets:
            continue
        reference = assets[0]
        if not isinstance(reference, str):
            raise ReviewError("collection plan preview assetが不正です")
        relative = Path(reference)
        unresolved = root / relative
        preview = unresolved.resolve()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not preview.is_relative_to(root)
            or unresolved.is_symlink()
            or not preview.is_file()
            or preview.suffix.lower() not in _MEDIA_SUFFIXES["thumbnail"]
        ):
            raise ReviewError(f"collection plan preview assetを安全に表示できません: {reference}")
        result.append((candidate["plan_id"], preview))
    return tuple(result)


def _display_text(value: object) -> str:
    return value if isinstance(value, str) and value else "未設定"


def _list_summary(value: object, key: str) -> str:
    if not isinstance(value, list):
        return "未設定"
    parts = [item[key] for item in value if isinstance(item, dict) and isinstance(item.get(key), str)]
    return " / ".join(parts) if parts else "未設定"


def _candidate_set_digest(candidates: tuple[ReviewCandidate, ...]) -> str:
    payload = "\n".join(f"{candidate.id}:{candidate.digest}" for candidate in candidates).encode()
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ReviewError(f"review artifactが通常fileではありません: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["ReviewResult", "run_review"]
