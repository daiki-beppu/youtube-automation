"""Safe thumbnail candidate review and approval finalization."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from PIL import Image, UnidentifiedImageError

from youtube_automation.application.review_lifecycle import ReviewSource, collection_root as _collection_root, review
from youtube_automation.application.review_lifecycle import sha256_file as _sha256
from youtube_automation.core.errors import ConfigError, ReviewError, ValidationError, WorkflowStateError
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.collections.workflow_state import update as update_workflow_state
from youtube_automation.domains.documents.review import ReviewCandidate, SelectionManifest
from youtube_automation.domains.thumbnail.archive import (
    ThumbnailArchiveUpdate,
    archive_approved_thumbnail_transaction,
)
from youtube_automation.infrastructure.browser import open_local_file
from youtube_automation.infrastructure.browser.selection_broker import SelectionBroker

ThumbnailArtifact = Literal["thumbnail", "main"]
ThumbnailReviewSource = Literal["web", "terminal", "automatic"]
ThumbnailReviewTransport = Literal["web", "terminal"]

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_THUMBNAIL = re.compile(r"^thumbnail-(?:codex-)?v[1-9][0-9]*\.(?:jpg|jpeg|png|webp)$", re.IGNORECASE)
_AB_THUMBNAIL = re.compile(
    r"^thumbnail-(?P<pattern>[A-Za-z0-9][A-Za-z0-9_-]{0,63})-v[1-9][0-9]*\.(?:jpg|jpeg|png|webp)$",
    re.IGNORECASE,
)
_MAIN = re.compile(r"^main-v[1-9][0-9]*\.(?:jpg|jpeg|png|webp)$", re.IGNORECASE)
_DIGEST = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class ThumbnailReviewCandidate:
    candidate_id: str
    artifact: ThumbnailArtifact
    pattern: str | None
    image: Path
    qa_path: Path
    image_digest: str
    qa_digest: str
    width: int
    height: int
    thumbnail_check: str
    comparison_qa: str
    metadata: str
    evidence: str
    constraints: str

    @property
    def digest(self) -> str:
        value = ":".join((self.candidate_id, self.artifact, self.pattern or "-", self.image_digest, self.qa_digest))
        return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class ThumbnailReviewResult:
    status: Literal["skipped", "terminal_required", "selected"]
    artifact_digest: str | None = None
    candidate_id: str | None = None
    candidates: tuple[str, ...] = ()
    html_path: Path | None = None


@dataclass(frozen=True)
class _Snapshot:
    manifest: SelectionManifest
    candidates: tuple[ThumbnailReviewCandidate, ...]

    def media(self) -> dict[str, Path]:
        return {candidate.candidate_id: candidate.image for candidate in self.candidates}


class _ThumbnailSource(ReviewSource):
    def __init__(self, collection: Path, artifact: ThumbnailArtifact, pattern: str | None) -> None:
        self.collection, self.kind, self.pattern = collection, artifact, pattern
        self.snapshot: _Snapshot | None = None

    @property
    def artifact(self):
        return "thumbnail"

    @property
    def html_path(self):
        return self.collection.resolve() / "tmp/reviews/thumbnail-selection.html"

    @property
    def compact_image_ids(self):
        return frozenset(c.id for c in self.snapshot.manifest.candidates) if self.snapshot else frozenset()

    def candidates(self):
        self.snapshot = build_thumbnail_review_snapshot(
            self.collection, self.kind, pattern=self.pattern, now=datetime.now(UTC)
        )
        return self.snapshot.manifest.candidates

    def media(self):
        assert self.snapshot is not None
        return tuple(self.snapshot.media().items())

    def digest(self, candidates):
        return _artifact_digest(self.snapshot.candidates) if self.snapshot else ""

    def commit(self, candidate):
        pass


def run_thumbnail_review(
    collection: Path,
    artifact: ThumbnailArtifact,
    *,
    pattern: str | None = None,
    automatic: bool = False,
    transport: ThumbnailReviewTransport = "web",
    timeout: float = 300,
    now: datetime | None = None,
) -> ThumbnailReviewResult:
    del now
    if automatic:
        return ThumbnailReviewResult(status="skipped")
    outcome = review(
        _ThumbnailSource(collection, artifact, pattern),
        transport,
        False,
        timeout,
        broker_factory=SelectionBroker,
        open_file=open_local_file,
    )
    return ThumbnailReviewResult(
        outcome.status, outcome.artifact_digest, outcome.candidate_id, outcome.candidates, outcome.html_path
    )


def build_thumbnail_review_snapshot(
    collection: Path,
    artifact: ThumbnailArtifact,
    *,
    pattern: str | None,
    now: datetime,
) -> _Snapshot:
    root = _collection_root(collection)
    if artifact == "main" and pattern is not None:
        raise ReviewError("textless mainにAB patternは指定できません")
    if pattern is not None and not _PATTERN.fullmatch(pattern):
        raise ReviewError(f"AB patternが不正です: {pattern}")
    candidates = _load_candidates(root, artifact, pattern)
    review_candidates = tuple(
        ReviewCandidate(
            item.candidate_id,
            item.image.name,
            item.digest,
            details=(
                ("確認目的", "文字付きthumbnail" if artifact == "thumbnail" else "textless main"),
                ("AB pattern", item.pattern or "なし"),
                ("画像寸法", f"{item.width} × {item.height}px"),
                ("yt-thumbnail-check", item.thumbnail_check),
                ("比較QA", item.comparison_qa),
                ("候補metadata", item.metadata),
                ("根拠", item.evidence),
                ("制約", item.constraints),
                ("画像SHA-256", item.image_digest),
            ),
        )
        for item in candidates
    )
    manifest = SelectionManifest.create(
        artifact="thumbnail",
        artifact_digest=_artifact_digest(candidates),
        candidates=review_candidates,
        now=now,
        lifetime=timedelta(minutes=5),
    )
    return _Snapshot(manifest, candidates)


def finalize_thumbnail_review_selection(
    collection: Path,
    *,
    artifact: ThumbnailArtifact,
    pattern: str | None,
    candidate_id: str,
    source: ThumbnailReviewSource,
    expected_artifact_digest: str,
    archive_config: Mapping[str, object] | None = None,
    channel_root: Path | None = None,
) -> Path:
    """Revalidate all evidence, then atomically copy and update the existing state owner."""
    if source not in {"web", "terminal", "automatic"}:
        raise ValidationError(f"thumbnail review sourceが不正です: {source}")
    if (archive_config is None) != (channel_root is None):
        raise ValidationError("archive_configとchannel_rootは両方指定するか両方省略してください")
    snapshot = build_thumbnail_review_snapshot(collection, artifact, pattern=pattern, now=datetime.now(UTC))
    if not _DIGEST.fullmatch(expected_artifact_digest) or snapshot.manifest.artifact_digest != expected_artifact_digest:
        raise ValidationError("画像またはQA結果のdigestがreview時点と一致しません")
    selected = next((item for item in snapshot.candidates if item.candidate_id == candidate_id), None)
    if selected is None or selected.artifact != artifact or selected.pattern != pattern:
        raise ValidationError("候補ID / artifact / patternの組がreview manifest allowlistと一致しません")

    target = _target_path(_collection_root(collection), selected)
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValidationError(f"正規成果物は通常fileまたは未作成pathである必要があります: {target}")
    original = target.read_bytes() if target.is_file() else None
    archive_update: ThumbnailArchiveUpdate | None = None
    try:
        _copy_candidate(selected, target)
        if artifact == "thumbnail" and pattern is None and archive_config is not None and channel_root is not None:
            archive_update = archive_approved_thumbnail_transaction(
                collection, archive_config=archive_config, channel_root=channel_root
            )

        def record(state: WorkflowState) -> None:
            state.record_thumbnail_review_selection(
                {
                    "schema_version": 1,
                    "source": source,
                    "candidate_id": candidate_id,
                    "artifact": artifact,
                    "pattern": pattern,
                    "image_sha256": selected.image_digest,
                    "qa_sha256": selected.qa_digest,
                    "artifact_digest": expected_artifact_digest,
                    "selected_at": datetime.now(UTC).isoformat(),
                }
            )

        update_workflow_state(_collection_root(collection) / "workflow-state.json", record)
    except (OSError, ConfigError, ValidationError, WorkflowStateError) as exc:
        if archive_update is not None:
            archive_update.rollback()
        _restore_target(target, original)
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(f"thumbnail承認の確定に失敗しました: {exc}") from exc
    return target


def _load_candidates(
    collection: Path, artifact: ThumbnailArtifact, pattern: str | None
) -> tuple[ThumbnailReviewCandidate, ...]:
    assets = collection / "10-assets"
    if assets.is_symlink() or not assets.is_dir():
        raise ReviewError(f"10-assets directoryが不正です: {assets}")
    result: list[ThumbnailReviewCandidate] = []
    for image in sorted(assets.iterdir()):
        if image.is_symlink() or not image.is_file():
            continue
        parsed = _candidate_kind(image.name)
        if parsed != (artifact, pattern):
            continue
        result.append(_load_candidate(image, artifact, pattern))
    if not result:
        raise ReviewError(f"review候補がありません: artifact={artifact}, pattern={pattern or '-'}")
    if len({item.candidate_id for item in result}) != len(result):
        raise ReviewError("thumbnail review candidate IDが重複しています")
    return tuple(result)


def _candidate_kind(name: str) -> tuple[ThumbnailArtifact, str | None] | None:
    if _THUMBNAIL.fullmatch(name):
        return "thumbnail", None
    if match := _AB_THUMBNAIL.fullmatch(name):
        pattern = match.group("pattern")
        if pattern.lower() != "codex":
            return "thumbnail", pattern
    if _MAIN.fullmatch(name):
        return "main", None
    return None


def _load_candidate(image: Path, artifact: ThumbnailArtifact, pattern: str | None) -> ThumbnailReviewCandidate:
    qa_path = image.with_suffix(f"{image.suffix}.review.json")
    if qa_path.is_symlink() or not qa_path.is_file():
        raise ReviewError(f"候補QA結果がありません: {qa_path}")
    try:
        document: object = json.loads(qa_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewError(f"候補QA結果を読み込めません: {qa_path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ReviewError(f"候補QA結果のrootはobjectである必要があります: {qa_path}")
    candidate_id = document.get("candidate_id")
    recorded_artifact = document.get("artifact")
    recorded_pattern = document.get("pattern")
    recorded_digest = document.get("image_sha256")
    thumbnail_check = document.get("thumbnail_check")
    comparison_qa = document.get("comparison_qa")
    metadata = document.get("metadata")
    evidence = document.get("evidence")
    constraints = document.get("constraints")
    image_digest = _sha256(image)
    if not isinstance(candidate_id, str) or not _ID.fullmatch(candidate_id):
        raise ReviewError(f"候補QAのcandidate_idが不正です: {qa_path}")
    if recorded_artifact != artifact or recorded_pattern != pattern:
        raise ReviewError(f"候補QAのartifact / patternが画像名と一致しません: {qa_path}")
    if recorded_digest != image_digest:
        raise ReviewError(f"候補QAの画像digestが実画像と一致しません: {image.name}")
    thumbnail_summary = _qa_summary(thumbnail_check, "thumbnail_check", qa_path)
    comparison_summary = _qa_summary(comparison_qa, "comparison_qa", qa_path)
    metadata_summary = _mapping_summary(metadata, "metadata", qa_path)
    evidence_summary = _string_list_summary(evidence, "evidence", qa_path)
    constraints_summary = _string_list_summary(constraints, "constraints", qa_path)
    try:
        with Image.open(image) as opened:
            width, height = opened.size
            opened.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise ReviewError(f"候補画像を検証できません: {image}: {exc}") from exc
    return ThumbnailReviewCandidate(
        candidate_id=candidate_id,
        artifact=artifact,
        pattern=pattern,
        image=image.resolve(),
        qa_path=qa_path.resolve(),
        image_digest=image_digest,
        qa_digest=_sha256(qa_path),
        width=width,
        height=height,
        thumbnail_check=thumbnail_summary,
        comparison_qa=comparison_summary,
        metadata=metadata_summary,
        evidence=evidence_summary,
        constraints=constraints_summary,
    )


def _qa_summary(value: object, name: str, path: Path) -> str:
    if not isinstance(value, dict) or not value:
        raise ReviewError(f"候補QAの{name}が欠落しています: {path}")
    status = value.get("status")
    summary = value.get("summary")
    if status not in {"passed", "failed", "not_applicable"} or not isinstance(summary, str) or not summary.strip():
        raise ReviewError(f"候補QAの{name}はstatusと非空summaryが必要です: {path}")
    return f"{status}: {summary.strip()}"


def _mapping_summary(value: object, name: str, path: Path) -> str:
    if not isinstance(value, dict) or not value or any(not isinstance(key, str) or not key for key in value):
        raise ReviewError(f"候補QAの{name}は非空objectである必要があります: {path}")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _string_list_summary(value: object, name: str, path: Path) -> str:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ReviewError(f"候補QAの{name}は非空文字列listである必要があります: {path}")
    return " / ".join(item.strip() for item in value)


def _target_path(collection: Path, candidate: ThumbnailReviewCandidate) -> Path:
    assets = collection / "10-assets"
    if candidate.artifact == "thumbnail":
        return assets / (f"thumbnail-{candidate.pattern}.jpg" if candidate.pattern else "thumbnail.jpg")
    return assets / f"main{candidate.image.suffix.lower()}"


def _copy_candidate(candidate: ThumbnailReviewCandidate, target: Path) -> None:
    if target.is_symlink():
        raise ValidationError(f"正規成果物にsymlinkは指定できません: {target}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}-review-", suffix=target.suffix, dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        if candidate.artifact == "thumbnail" and candidate.image.suffix.lower() not in {".jpg", ".jpeg"}:
            with Image.open(candidate.image) as opened:
                opened.convert("RGB").save(temporary, "JPEG", quality=95)
        else:
            shutil.copyfile(candidate.image, temporary)
        os.replace(temporary, target)
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError(f"候補画像を正規成果物へ確定できません: {candidate.image} -> {target}: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _restore_target(target: Path, original: bytes | None) -> None:
    if original is None:
        target.unlink(missing_ok=True)
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}-rollback-", suffix=target.suffix, dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(original)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact_digest(candidates: tuple[ThumbnailReviewCandidate, ...]) -> str:
    value = "\n".join(f"{candidate.candidate_id}:{candidate.digest}" for candidate in candidates)
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = [
    "ThumbnailReviewCandidate",
    "ThumbnailReviewResult",
    "build_thumbnail_review_snapshot",
    "finalize_thumbnail_review_selection",
    "run_thumbnail_review",
]
