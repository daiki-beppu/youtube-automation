"""Safe master-audio review and finalization through the shared lifecycle."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
from youtube_automation.infrastructure.media.probe import probe_duration

ReviewTransport = Literal["web", "terminal"]
ReviewSource = Literal["web", "terminal", "automatic"]
_AUDIO_EXTENSIONS = frozenset({".m4a", ".wav", ".flac", ".aac", ".mp3"})


@dataclass(frozen=True)
class MasterAudioCandidate:
    candidate_id: str
    name: str
    source: str
    path: Path
    duration_seconds: float
    size_bytes: int
    raw_master: bool
    loudness: str
    selection: str
    digest: str


@dataclass(frozen=True)
class MasterAudioReviewResult:
    status: Literal["terminal_required", "selected"]
    artifact_digest: str | None = None
    candidate_id: str | None = None
    candidates: tuple[str, ...] = ()
    html_path: Path | None = None


@dataclass(frozen=True)
class MasterAudioReviewSnapshot:
    manifest: SelectionManifest
    candidates: tuple[MasterAudioCandidate, ...]

    def media(self) -> dict[str, Path]:
        return {candidate.candidate_id: candidate.path for candidate in self.candidates}


def review_and_finalize_master_audio(
    collection: Path,
    *,
    skip_manual_mastering: bool,
    skip_audio_approval: bool,
    transport: ReviewTransport,
    candidate_id: str | None,
    main_repo_root: Path | None,
    now: datetime | None = None,
    timeout: float = 300,
) -> MasterAudioReviewResult:
    """Resolve candidates once, optionally review them, then finalize one revalidated ID."""
    instant = now or datetime.now(UTC)
    snapshot = build_master_audio_review_snapshot(
        collection,
        skip_manual_mastering=skip_manual_mastering,
        main_repo_root=main_repo_root,
        now=instant,
    )
    candidate_ids = tuple(candidate.candidate_id for candidate in snapshot.candidates)
    destination: Path | None = None
    source: ReviewSource
    selected_id: str
    if skip_audio_approval:
        if candidate_id is None and len(candidate_ids) > 1:
            return _terminal_required(snapshot)
        selected_id = candidate_id or candidate_ids[0]
        source = "automatic" if candidate_id is None else "terminal"
    elif transport == "terminal":
        if candidate_id is None:
            return _terminal_required(snapshot)
        selected_id = candidate_id
        source = "terminal"
    else:
        if candidate_id is not None:
            raise ValidationError("candidate-idはterminal review専用です")
        with SelectionBroker(snapshot.manifest) as broker:
            destination = _display(collection, snapshot, broker.endpoint)
            selection = broker.wait(timeout=timeout)
        current = build_master_audio_review_snapshot(
            collection,
            skip_manual_mastering=skip_manual_mastering,
            main_repo_root=main_repo_root,
            now=instant,
        )
        _require_same_selection(snapshot, current, selection.candidate_id, selection.artifact_digest)
        selected_id = selection.candidate_id
        source = "web"

    if selected_id not in candidate_ids:
        raise ValidationError(f"候補IDがreview manifest allowlistにありません: {selected_id}")
    finalize_master_audio_selection(
        collection,
        skip_manual_mastering=skip_manual_mastering,
        candidate_id=selected_id,
        source=source,
        expected_artifact_digest=snapshot.manifest.artifact_digest,
        main_repo_root=main_repo_root,
    )
    return MasterAudioReviewResult(
        status="selected",
        artifact_digest=snapshot.manifest.artifact_digest,
        candidate_id=selected_id,
        candidates=candidate_ids,
        html_path=destination,
    )


def build_master_audio_review_snapshot(
    collection: Path,
    *,
    skip_manual_mastering: bool,
    main_repo_root: Path | None,
    now: datetime,
) -> MasterAudioReviewSnapshot:
    root, raw_master = _review_state(collection)
    inputs = _candidate_inputs(root, raw_master, main_repo_root)
    if not inputs:
        if not skip_manual_mastering:
            raise ReviewError("最終マスター候補がありません。manual mastering完了後に再実行してください")
        raw_path = root / "01-master" / raw_master
        _require_audio_file(raw_path)
        inputs = (("worktree", raw_path, True),)
    loudness = _loudness_summary(root)
    selection = _selection_summary(root)
    candidates = tuple(
        _load_candidate(source, path, raw, loudness=loudness, selection=selection) for source, path, raw in inputs
    )
    manifest_candidates = tuple(
        ReviewCandidate(
            candidate.candidate_id,
            candidate.name,
            candidate.digest,
            details=(
                ("候補ID", candidate.candidate_id),
                ("source", candidate.source),
                ("ファイル名", candidate.name),
                ("形式", candidate.path.suffix.lower().removeprefix(".").upper()),
                ("duration", f"{candidate.duration_seconds:.2f}秒"),
                ("size", f"{candidate.size_bytes} bytes"),
                ("採用種別", "raw master直採用" if candidate.raw_master else "最終マスター候補"),
                ("loudness検査", candidate.loudness),
                ("選曲情報", candidate.selection),
            ),
        )
        for candidate in candidates
    )
    manifest = SelectionManifest.create(
        artifact="audio",
        artifact_digest=_artifact_digest(candidates),
        candidates=manifest_candidates,
        now=now,
        lifetime=timedelta(minutes=5),
    )
    return MasterAudioReviewSnapshot(manifest, candidates)


def finalize_master_audio_selection(
    collection: Path,
    *,
    skip_manual_mastering: bool,
    candidate_id: str,
    source: ReviewSource,
    expected_artifact_digest: str,
    main_repo_root: Path | None,
) -> Path:
    if source not in {"web", "terminal", "automatic"}:
        raise ValidationError(f"master audio review sourceが不正です: {source}")
    snapshot = build_master_audio_review_snapshot(
        collection,
        skip_manual_mastering=skip_manual_mastering,
        main_repo_root=main_repo_root,
        now=datetime.now(UTC),
    )
    if snapshot.manifest.artifact_digest != expected_artifact_digest:
        raise ValidationError("音源または検査結果のdigestがreview時点と一致しません")
    selected = next((candidate for candidate in snapshot.candidates if candidate.candidate_id == candidate_id), None)
    if selected is None:
        raise ValidationError(f"候補IDがreview manifest allowlistにありません: {candidate_id}")
    root = _collection_root(collection)
    target = root / "01-master" / selected.name
    if target.is_symlink():
        raise ValidationError(f"master audio確定先がsymlinkです: {target}")
    previous = target.read_bytes() if target.is_file() and selected.source == "main" else None
    copied = selected.source == "main"
    try:
        if copied:
            shutil.copy2(selected.path, target)
        _adopt(root / "workflow-state.json", selected.name)
    except (OSError, WorkflowStateError) as error:
        if copied:
            if previous is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(previous)
        raise ValidationError(f"master audio確定に失敗しました: {error}") from error
    return target


def _candidate_inputs(
    collection: Path, raw_master: str, main_repo_root: Path | None
) -> tuple[tuple[str, Path, bool], ...]:
    master_dirs = [("worktree", collection / "01-master")]
    main_master = _main_master_dir(collection, main_repo_root)
    if main_master is not None:
        master_dirs.append(("main", main_master))
    result: list[tuple[str, Path, bool]] = []
    seen: set[tuple[str, Path]] = set()
    for source, directory in master_dirs:
        if directory.is_symlink() or not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.name == raw_master or path.is_symlink() or not path.is_file():
                continue
            if path.suffix.lower() not in _AUDIO_EXTENSIONS:
                continue
            key = (path.name, path.resolve())
            if key in seen:
                continue
            seen.add(key)
            result.append((source, path.resolve(), False))
    return tuple(result)


def _main_master_dir(collection: Path, main_repo_root: Path | None) -> Path | None:
    local = collection / "01-master"
    root = main_repo_root or _discover_main_repo_root()
    if root is None:
        return None
    candidate = root.resolve() / "collections/planning" / collection.name / "01-master"
    return None if candidate == local.resolve() else candidate


def _discover_main_repo_root() -> Path | None:
    repository = Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    common = Path(result.stdout.strip())
    return None if common == repository / ".git" else common.parent


def _load_candidate(
    source: str,
    path: Path,
    raw_master: bool,
    *,
    loudness: str,
    selection: str,
) -> MasterAudioCandidate:
    _require_audio_file(path)
    duration = probe_duration(path)
    if duration is None or duration <= 0:
        raise ReviewError(f"ffprobeでmaster audioを読み取れません: {path}")
    size = path.stat().st_size
    file_digest = _sha256(path)
    candidate_id = f"{source}:{path.name}"
    digest_value = "\0".join(
        (candidate_id, file_digest, str(size), str(duration), str(raw_master), loudness, selection)
    )
    return MasterAudioCandidate(
        candidate_id=candidate_id,
        name=path.name,
        source=source,
        path=path,
        duration_seconds=duration,
        size_bytes=size,
        raw_master=raw_master,
        loudness=loudness,
        selection=selection,
        digest=hashlib.sha256(digest_value.encode()).hexdigest(),
    )


def _review_state(collection: Path) -> tuple[Path, str]:
    root = _collection_root(collection)
    try:
        state = read_workflow_state(root / "workflow-state.json")
    except WorkflowStateError as error:
        raise ReviewError(f"workflow-state.jsonを読めません: {error}") from error
    assets = state.assets
    if state.phase != "prepared" or assets is None or assets.master_audio is not None:
        raise ReviewError("master audio reviewはpreparedの未確定collectionだけ実行できます")
    raw_master = assets.raw_master
    if raw_master is None or raw_master != Path(raw_master).name:
        raise ReviewError("assets.raw_masterは安全なファイル名が必要です")
    return root, raw_master


def _collection_root(collection: Path) -> Path:
    if collection.is_symlink() or not collection.is_dir():
        raise ReviewError(f"collection directoryが不正です: {collection}")
    return collection.resolve()


def _require_audio_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or path.suffix.lower() not in _AUDIO_EXTENSIONS:
        raise ReviewError(f"master audio fileが不正です: {path}")


def _loudness_summary(collection: Path) -> str:
    receipt = collection / "01-master/.loudness-receipt.json"
    if not receipt.exists():
        return "未記録"
    if receipt.is_symlink() or not receipt.is_file():
        raise ReviewError(f"loudness receiptが不正です: {receipt}")
    try:
        payload = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReviewError(f"loudness receiptを読めません: {receipt}") from error
    if not isinstance(payload, Mapping):
        raise ReviewError("loudness receiptのrootはobjectが必要です")
    status = payload.get("status")
    measured = payload.get("measured_deviation_lu")
    limit = payload.get("max_deviation_lu")
    if status not in {"PASS", "FAIL"} or not isinstance(measured, int | float) or not isinstance(limit, int | float):
        raise ReviewError("loudness receiptの検査結果が不正です")
    return f"{status}（実測 {float(measured):.2f} LU / 上限 {float(limit):.2f} LU）"


def _selection_summary(collection: Path) -> str:
    log = collection / "01-master/.selection.log"
    if not log.exists():
        return "未記録"
    if log.is_symlink() or not log.is_file():
        raise ReviewError(f"selection logが不正です: {log}")
    try:
        value = log.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ReviewError(f"selection logを読めません: {log}") from error
    return value.strip()[:4096] or "空"


def _artifact_digest(candidates: tuple[MasterAudioCandidate, ...]) -> str:
    payload = "\n".join(f"{candidate.candidate_id}:{candidate.digest}" for candidate in candidates)
    return hashlib.sha256(payload.encode()).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _terminal_required(snapshot: MasterAudioReviewSnapshot) -> MasterAudioReviewResult:
    return MasterAudioReviewResult(
        status="terminal_required",
        artifact_digest=snapshot.manifest.artifact_digest,
        candidates=tuple(candidate.candidate_id for candidate in snapshot.candidates),
    )


def _display(collection: Path, snapshot: MasterAudioReviewSnapshot, endpoint: str) -> Path:
    destination = _collection_root(collection) / "tmp/reviews/master-audio.html"
    media = snapshot.media()
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
        raise ReviewError(f"browserでmaster audio review HTMLを開けません: {destination.resolve()}")
    return destination.resolve()


def _require_same_selection(
    original: MasterAudioReviewSnapshot,
    current: MasterAudioReviewSnapshot,
    candidate_id: str,
    artifact_digest: str,
) -> None:
    if original.manifest.artifact_digest != artifact_digest:
        raise ReviewError("brokerが返したartifact digestがreview対象と一致しません")
    if current.manifest.artifact_digest != artifact_digest:
        raise ReviewError("review中に音源または検査結果が変わりました")
    before = next((candidate for candidate in original.candidates if candidate.candidate_id == candidate_id), None)
    after = next((candidate for candidate in current.candidates if candidate.candidate_id == candidate_id), None)
    if before is None or after is None or before.digest != after.digest:
        raise ReviewError("review中に選択候補が変わりました")


def _adopt(state_path: Path, selected: str) -> None:
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def transition(state: WorkflowState) -> None:
        assets = state.assets
        if state.phase != "prepared" or assets is None or assets.master_audio is not None:
            raise WorkflowStateError("master audio transition is no longer pending")
        assets.master_audio = selected
        state.phase = "mastered"
        state["updated_at"] = timestamp

    update_workflow_state(state_path, transition)


__all__ = [
    "MasterAudioReviewResult",
    "MasterAudioReviewSnapshot",
    "build_master_audio_review_snapshot",
    "finalize_master_audio_selection",
    "review_and_finalize_master_audio",
]
