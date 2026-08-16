"""Read-only workflow status view model built from canonical state and artifacts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from youtube_automation.core.errors import ValidationError, WorkflowStateError
from youtube_automation.domains.collections.workflow_state import WorkflowState, read_or_none
from youtube_automation.domains.documents.workflow_status import (
    ArtifactStatus,
    ArtifactStatusView,
    CollectionStatus,
    CollectionStatusView,
    WorkflowStatusSnapshot,
)
from youtube_automation.infrastructure.media.collection_paths import CollectionPaths


def build_workflow_status_snapshot(channel_dir: Path, *, now: datetime) -> WorkflowStatusSnapshot:
    """Build an ephemeral status snapshot without changing workflow state or artifacts."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValidationError("workflow status の現在時刻には timezone が必要です")
    items: list[CollectionStatusView] = []
    for area in ("planning", "live"):
        area_dir = channel_dir / "collections" / area
        if not area_dir.is_dir():
            continue
        for collection_dir in sorted(path for path in area_dir.iterdir() if path.is_dir() and not path.is_symlink()):
            items.append(_collection_view(collection_dir, area=area, now=now))
    return WorkflowStatusSnapshot(generated_at=now, collections=tuple(items))


def _collection_view(collection_dir: Path, *, area: str, now: datetime) -> CollectionStatusView:
    state_path = collection_dir / "workflow-state.json"
    try:
        state = read_or_none(state_path)
        if state is None:
            raise WorkflowStateError(f"workflow-state.json がありません: {state_path}")
        return _valid_collection_view(collection_dir, area=area, state=state, now=now)
    except WorkflowStateError as exc:
        return CollectionStatusView(
            name=collection_dir.name,
            slug=collection_dir.name,
            status="live" if area == "live" else "planning",
            phase="不明",
            blocker=str(exc),
            next_action="/wf-new",
            updated_at="不明",
            stalled_for="不明",
            stale=False,
            warnings=(str(exc),),
            artifacts=_artifact_views(collection_dir, None),
        )


def _valid_collection_view(
    collection_dir: Path, *, area: str, state: WorkflowState, now: datetime
) -> CollectionStatusView:
    phase = state.phase or "不明"
    stage = state.stage
    warnings: list[str] = []
    if stage is not None and stage != area:
        warnings.append(f"配置先 collections/{area} と workflow state stage={stage} が一致しません")
    updated_at, stalled_for, stale, timestamp_warning = _timestamp_view(state, now)
    if timestamp_warning is not None:
        warnings.append(timestamp_warning)
    artifacts = _artifact_views(collection_dir, state)
    warnings.extend(item.detail for item in artifacts if item.status == "inconsistent")
    status: CollectionStatus
    if phase == "complete":
        status = "complete"
    elif stage == "live" or area == "live":
        status = "live"
    else:
        status = "planning"
    video_id = state.upload.video_id if state.upload is not None else None
    next_action = "完了" if phase == "complete" and video_id else "/wf-new" if phase == "planning" else "/wf-next"
    inconsistent = next(
        (
            item
            for key in ("master_audio", "master_video", "thumbnail", "music_prompt", "plan")
            for item in artifacts
            if item.key == key and item.status == "inconsistent"
        ),
        None,
    )
    if inconsistent is not None:
        blocker = f"{inconsistent.label}: {inconsistent.detail}"
    elif warnings:
        blocker = warnings[0]
    elif phase == "complete":
        blocker = "なし"
    else:
        blocker = _phase_blocker(phase)
    return CollectionStatusView(
        name=state.collection_name or collection_dir.name,
        slug=collection_dir.name,
        status=status,
        phase=phase,
        blocker=blocker,
        next_action=next_action,
        updated_at=updated_at,
        stalled_for=stalled_for,
        stale=stale,
        warnings=tuple(warnings),
        artifacts=artifacts,
    )


def _timestamp_view(state: WorkflowState, now: datetime) -> tuple[str, str, bool, str | None]:
    value = state.get("updated_at")
    if not isinstance(value, str):
        return "不明", "不明", False, "workflow state updated_at がありません"
    try:
        updated = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value, "不明", False, f"workflow state updated_at が不正です: {value}"
    if updated.tzinfo is None or updated.utcoffset() is None:
        return value, "不明", False, f"workflow state updated_at に timezone がありません: {value}"
    elapsed = max(now - updated, now - now)
    hours = int(elapsed.total_seconds() // 3600)
    days, remaining_hours = divmod(hours, 24)
    stalled = f"{days}日 {remaining_hours}時間" if days else f"{remaining_hours}時間"
    return updated.strftime("%Y-%m-%d %H:%M %Z"), stalled, elapsed.days >= 7, None


def _artifact_views(collection_dir: Path, state: WorkflowState | None) -> tuple[ArtifactStatusView, ...]:
    paths = CollectionPaths(collection_dir)
    assets = state.assets if state is not None else None
    planning = state.planning if state is not None else None
    upload = state.upload if state is not None else None
    plan_file = paths.docs_dir / "plan_proposals.json"
    engine = state.music_engine if state is not None else None
    prompt_file = paths.docs_dir / ("lyria-prompt.json" if engine == "lyria" else "suno-prompts.json")
    plan_claim = planning.get("generated") is True if planning is not None else False
    prompt_claim = assets.get("music_prompts") is True if assets is not None else False
    thumbnail_claim = bool(assets.thumbnail) if assets is not None else False
    master_audio_claim = assets.master_audio if assets is not None else None
    master_video_claim = assets.master_video if assets is not None else None
    return (
        _boolean_artifact("plan", "企画", plan_claim, plan_file, plan_file.relative_to(collection_dir).as_posix()),
        _boolean_artifact("thumbnail", "サムネイル", thumbnail_claim, paths.find_thumbnail(), "10-assets/thumbnail.*"),
        _boolean_artifact(
            "music_prompt",
            "音楽プロンプト",
            prompt_claim,
            prompt_file,
            prompt_file.relative_to(collection_dir).as_posix(),
        ),
        _named_artifact(
            "master_audio",
            "master音源",
            master_audio_claim,
            paths.master_dir,
            suffixes=(".mp3", ".wav", ".flac", ".m4a"),
        ),
        _named_artifact("master_video", "master動画", master_video_claim, paths.master_dir, suffixes=(".mp4", ".mov")),
        ArtifactStatusView(
            key="publish",
            label="公開",
            status=(
                "complete"
                if upload is not None and upload.video_id
                else "inconsistent"
                if state is not None and state.phase == "complete"
                else "missing"
            ),
            detail=f"YouTube video_id: {upload.video_id}"
            if upload is not None and upload.video_id
            else "video_id 未記録",
        ),
    )


def _boolean_artifact(key: str, label: str, claimed: bool, path: Path | None, display: str) -> ArtifactStatusView:
    exists = path is not None and path.is_file() and not path.is_symlink()
    if claimed == exists:
        status: ArtifactStatus = "complete" if claimed else "missing"
        detail = display if claimed else f"{display} 未生成"
    else:
        status = "inconsistent"
        detail = f"state={'完了' if claimed else '未完了'} / 実成果物={'あり' if exists else 'なし'}: {display}"
    return ArtifactStatusView(key=key, label=label, status=status, detail=detail)


def _named_artifact(
    key: str, label: str, filename: str | None, directory: Path, *, suffixes: tuple[str, ...]
) -> ArtifactStatusView:
    safe_name = filename is not None and Path(filename).name == filename
    path = directory / filename if safe_name and filename is not None else None
    exists = path is not None and path.is_file() and not path.is_symlink()
    if filename is None:
        untracked = (
            next(
                (
                    candidate
                    for candidate in sorted(directory.iterdir())
                    if candidate.is_file() and not candidate.is_symlink() and candidate.suffix.lower() in suffixes
                ),
                None,
            )
            if directory.is_dir()
            else None
        )
        if untracked is not None:
            return ArtifactStatusView(
                key=key,
                label=label,
                status="inconsistent",
                detail=f"state は未完了ですが実成果物があります: 01-master/{untracked.name}",
            )
        return ArtifactStatusView(key=key, label=label, status="missing", detail="未生成")
    if safe_name and exists:
        return ArtifactStatusView(key=key, label=label, status="complete", detail=f"01-master/{filename}")
    detail = f"state は {filename} を参照しますが実成果物がありません"
    if not safe_name:
        detail = f"state の成果物名が不正です: {filename}"
    return ArtifactStatusView(key=key, label=label, status="inconsistent", detail=detail)


def _phase_blocker(phase: str) -> str:
    return {
        "planning": "企画の完了待ち",
        "prepared": "master成果物の生成待ち",
        "mastered": "動画または概要欄の準備待ち",
        "publishing": "YouTube公開の完了待ち",
    }.get(phase, "workflow state の確認が必要です")
