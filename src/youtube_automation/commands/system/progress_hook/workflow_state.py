"""下流チャンネルの正規状態から進捗図の完了段を解決する。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from youtube_automation.core.errors import AutomationError
from youtube_automation.domains.collections.inventory import iter_collections
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.domains.documents.operational_artifacts import resolve_artifacts
from youtube_automation.domains.post_publish import verify_post_publish_completion

STAGES = ("企画", "音源生成", "マスター化", "動画化", "サムネイル", "アップロード", "公開後処理", "分析")

# /wf-status が定義する v2 phase 語彙を正規の段判定にも使う。
WF_STATUS_PHASES = frozenset({"planning", "prepared", "cloud_owned", "mastered", "publishing", "complete"})


@dataclass(frozen=True)
class ProgressSnapshot:
    """選択したコレクションから解決済みの完了段。"""

    completed_stages: frozenset[str]


def _read_object(path: Path) -> Mapping[object, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def _find_channel_root(cwd: Path) -> Path | None:
    for candidate in (cwd, *cwd.parents):
        if (candidate / "collections").is_dir():
            return candidate
    return None


def _collection_paths(root: Path) -> list[Path]:
    # state が実在する collection だけを従来どおり選択候補に残す。
    return [
        record.directory for record in iter_collections(root) if (record.directory / "workflow-state.json").is_file()
    ]


def _select_collection(paths: list[Path], command: str | None) -> Path | None:
    if not paths:
        return None
    if command is not None:
        named = [path for path in paths if path.name in command]
        if named:
            return max(named, key=lambda path: len(path.name))
    return max(paths, key=lambda path: (path / "workflow-state.json").stat().st_mtime_ns)


def _skip_manual_mastering(root: Path) -> bool:
    config_path = root / "config" / "channel" / "workflow.json"
    if not config_path.is_file():
        return False
    config = _read_object(config_path)
    workflow = config.get("workflow")
    if not isinstance(workflow, Mapping):
        raise ValueError("workflow must be an object")
    wf_next = workflow.get("wf_next", {})
    if not isinstance(wf_next, Mapping):
        raise ValueError("workflow.wf_next must be an object")
    value = wf_next.get("skip_manual_mastering", False)
    if not isinstance(value, bool):
        raise ValueError("workflow.wf_next.skip_manual_mastering must be boolean")
    return value


def _file_asset_present(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _video_id(state: WorkflowState) -> str | None:
    upload = state.upload
    value = upload.video_id if upload is not None else None
    return value if value else None


def _publish_followup_complete(root: Path, collection: Path, video_id: str | None) -> bool:
    if video_id is None:
        return False
    try:
        verify_post_publish_completion(root, collection)
    except AutomationError:
        return False
    return True


def _publish_date(state: WorkflowState) -> date | None:
    upload = state.upload
    value = upload.publish_at if upload is not None else None
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _analysis_complete(root: Path, published_on: date | None) -> bool:
    if published_on is None:
        return False
    reports = resolve_artifacts(root, "reports/analysis_*.json")
    published_marker = Path(f"published_{published_on:%Y%m%d}.json")
    return bool(reports.valid) and not reports.freshness(against=published_marker).is_stale


def _completed_stages(root: Path, collection: Path, state: WorkflowState) -> frozenset[str]:
    phase = state.phase
    if phase not in WF_STATUS_PHASES:
        raise ValueError(f"unsupported workflow phase: {phase!r}")
    assets = state.assets
    if assets is None:
        raise ValueError("assets must be an object")

    criteria = (
        ("企画", phase != "planning"),
        ("音源生成", _file_asset_present(assets.raw_master)),
        (
            "マスター化",
            _file_asset_present(assets.master_audio)
            or (_skip_manual_mastering(root) and _file_asset_present(assets.raw_master)),
        ),
        ("動画化", _file_asset_present(assets.master_video)),
        ("サムネイル", state.thumbnail_approved),
        ("アップロード", phase == "complete"),
        ("公開後処理", _publish_followup_complete(root, collection, _video_id(state))),
        ("分析", _analysis_complete(root, _publish_date(state))),
    )
    return frozenset(stage for stage, complete in criteria if complete)


def load_progress_snapshot(cwd: str | None, command: str | None) -> ProgressSnapshot | None:
    """コレクションが無い、または状態を安全に読めない場合は None を返し、表示可否の判定を呼び出し側へ委ねる。"""

    if cwd is None:
        return None
    try:
        root = _find_channel_root(Path(cwd).resolve())
        if root is None:
            return None
        collection = _select_collection(_collection_paths(root), command)
        if collection is None:
            return None
        state_path = collection / "workflow-state.json"
        state = read_workflow_state(state_path)
        return ProgressSnapshot(_completed_stages(root, collection, state))
    except (AutomationError, OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
