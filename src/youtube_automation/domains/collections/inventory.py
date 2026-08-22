"""チャンネル内 collection の決定的で安全な inventory。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from youtube_automation.core.errors import WorkflowStateError
from youtube_automation.domains.collections.workflow_state import Stage, WorkflowState, read

_DEFAULT_STAGES: tuple[Stage, ...] = ("planning", "live")
_SUPPORTED_STAGES = frozenset(_DEFAULT_STAGES)


@dataclass(frozen=True, slots=True)
class UnreadableWorkflowState:
    """読み込めなかった workflow-state.json の明示的な値。"""

    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class CollectionRecord:
    """collection directory とその読み取り済み workflow state。"""

    directory: Path
    stage: Stage
    state: WorkflowState | UnreadableWorkflowState


def _validate_stages(stages: tuple[Stage, ...]) -> None:
    seen: set[Stage] = set()
    for stage in stages:
        if stage not in _SUPPORTED_STAGES:
            raise WorkflowStateError(f"unsupported collection stage: {stage}")
        if stage in seen:
            raise WorkflowStateError(f"duplicate collection stage: {stage}")
        seen.add(stage)


def _require_directory(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise WorkflowStateError(f"{label} must not be a symlink: {path}")
    if not path.is_dir():
        raise WorkflowStateError(f"{label} is not a directory: {path}")


def iter_collections(
    channel_dir: Path,
    stages: tuple[Stage, ...] = _DEFAULT_STAGES,
) -> tuple[CollectionRecord, ...]:
    """指定 stage の collection と state を名前順で返す。

    ``.`` / ``_`` で始まる名前は予約領域として除外する。構造上の hazard
    （symlink と stage 間の同名 collection）は fail loud とし、個々の state の
    読取不能だけは :class:`UnreadableWorkflowState` として呼び出し側へ渡す。
    """

    _validate_stages(stages)
    collections_root = channel_dir / "collections"
    if not collections_root.exists() and not collections_root.is_symlink():
        return ()
    _require_directory(collections_root, label="collections directory")

    records: list[CollectionRecord] = []
    names: dict[str, Stage] = {}
    for stage in stages:
        stage_dir = collections_root / stage
        if not stage_dir.exists() and not stage_dir.is_symlink():
            continue
        _require_directory(stage_dir, label=f"collection stage {stage}")
        try:
            entries = sorted(stage_dir.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            raise WorkflowStateError(f"collection stage could not be read: {stage_dir}") from exc
        for directory in entries:
            if directory.name.startswith((".", "_")):
                continue
            if directory.is_symlink():
                raise WorkflowStateError(f"collection must not be a symlink: {directory}")
            if not directory.is_dir():
                continue
            previous_stage = names.get(directory.name)
            if previous_stage is not None:
                raise WorkflowStateError(
                    f"duplicate collection name across stages: {directory.name} ({previous_stage}, {stage})"
                )
            names[directory.name] = stage
            resolved = directory.resolve(strict=True)
            state_path = resolved / "workflow-state.json"
            try:
                state: WorkflowState | UnreadableWorkflowState = read(state_path)
            except WorkflowStateError as exc:
                state = UnreadableWorkflowState(path=state_path, reason=str(exc))
            records.append(CollectionRecord(directory=resolved, stage=stage, state=state))

    return tuple(sorted(records, key=lambda record: record.directory.name))
