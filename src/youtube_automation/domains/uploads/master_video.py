"""公開用マスター動画の選択規則。アップロード実行から独立して検証にも使う。"""

from pathlib import Path

from youtube_automation.core.errors import ValidationError, WorkflowStateError
from youtube_automation.domains.collections.paths import CollectionPaths
from youtube_automation.domains.collections.workflow_state import read_or_none as read_workflow_state_or_none
from youtube_automation.infrastructure.filesystem import glob_files, path_is_file


def resolve_master_video(collection_dir: Path) -> Path:
    """workflow-state の明示値を優先し、Preview をマスター扱いしない。"""
    paths = CollectionPaths(collection_dir)
    state_path = paths.workflow_state_path
    try:
        state = read_workflow_state_or_none(state_path)
    except WorkflowStateError as exc:
        if "root must be an object" in str(exc):
            raise ValidationError("workflow-state.json root は object である必要があります") from exc
        if "::assets must be an object" in str(exc):
            raise ValidationError("workflow-state.json::assets は object である必要があります") from exc
        raise ValidationError(f"workflow-state.json を読めません: {state_path}: {exc}") from exc
    if state is not None:
        assets = state.assets
        try:
            configured = assets.master_video if assets is not None else None
        except WorkflowStateError as exc:
            raise ValidationError(
                "workflow-state.json::assets.master_video は .mp4 のファイル名で指定してください"
            ) from exc
        if configured is not None:
            return _configured_master_video(paths, configured)

    candidates = [
        path
        for path in sorted(glob_files(paths.movie_dir, "*master*.mp4"))
        if not path.name.lower().endswith("-preview.mp4")
    ]
    candidates.extend(
        path
        for path in sorted(glob_files(paths.master_dir, "*.mp4"))
        if not path.name.lower().endswith("-preview.mp4") and path not in candidates
    )
    if not candidates:
        raise ValidationError("マスター動画ファイルが見つかりません（*-Preview.mp4 は対象外）")
    return candidates[0]


def _configured_master_video(paths: CollectionPaths, configured: str) -> Path:
    """Require an existing non-preview MP4 for an explicit workflow selection."""
    configured_path = Path(configured)
    if configured_path.name != configured or configured_path.suffix.lower() != ".mp4":
        raise ValidationError("workflow-state.json::assets.master_video は .mp4 のファイル名で指定してください")
    selected = paths.master_dir / configured
    if not path_is_file(selected):
        raise ValidationError(f"assets.master_video のファイルが存在しません: {selected}")
    if selected.name.lower().endswith("-preview.mp4"):
        raise ValidationError(f"assets.master_video が Preview を指しています: {selected.name}")
    return selected
