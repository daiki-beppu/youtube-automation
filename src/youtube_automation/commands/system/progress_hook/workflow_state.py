"""下流チャンネルの正規状態から進捗図の完了段を解決する。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from youtube_automation.core.errors import AutomationError
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.domains.documents.schema_registry import RepositorySchema
from youtube_automation.infrastructure.documents.publishing import read_published_json_document

STAGES = ("企画", "音源生成", "マスター化", "動画化", "サムネイル", "アップロード", "公開後処理", "分析")

# /wf-status が定義する v2 phase 語彙を正規の段判定にも使う。
WF_STATUS_PHASES = frozenset({"planning", "prepared", "mastered", "publishing", "complete"})
_ANALYSIS_REPORT = re.compile(r"analysis_(\d{8})\.json\Z")


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
    paths: list[Path] = []
    for location in ("planning", "live"):
        base = root / "collections" / location
        if base.is_dir():
            paths.extend(path.parent for path in base.glob("*/workflow-state.json") if path.is_file())
    return paths


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
    community_path = collection / "20-documentation" / "community-post.txt"
    if not community_path.is_file() or not community_path.read_text(encoding="utf-8").strip():
        return False
    config_path = root / "config" / "channel" / "pinned-comment.json"
    if not config_path.is_file():
        return False
    config = _read_object(config_path)
    pinned = config.get("pinned_comment")
    if not isinstance(pinned, Mapping):
        return False
    history_file = pinned.get("history_file")
    if not isinstance(history_file, str) or not history_file:
        return False
    path = (root / history_file).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return False
    history = _read_object(path)
    posted = history.get("posted")
    return history.get("schema_version") == 1 and isinstance(posted, Mapping) and video_id in posted


def _publish_date(state: WorkflowState) -> date | None:
    upload = state.upload
    value = upload.publish_at if upload is not None else None
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _analysis_complete(root: Path, published_on: date | None) -> bool:
    if published_on is None:
        return False
    reports = root / "reports"
    if not reports.is_dir():
        return False
    for path in reports.glob("analysis_*.json"):
        match = _ANALYSIS_REPORT.fullmatch(path.name)
        if path.is_file() and match is not None:
            try:
                report_date = datetime.strptime(match.group(1), "%Y%m%d").date()
            except ValueError:
                continue
            if report_date >= published_on:
                read_published_json_document(path, RepositorySchema.ANALYSIS_REPORT)
                return True
    return False


def _completed_stages(root: Path, collection: Path, state: WorkflowState) -> frozenset[str]:
    phase = state.phase
    if phase not in WF_STATUS_PHASES:
        raise ValueError(f"unsupported workflow phase: {phase!r}")
    assets = state.assets
    if assets is None:
        raise ValueError("assets must be an object")

    completed: set[str] = set()
    if phase != "planning":
        completed.add("企画")
    if _file_asset_present(assets.raw_master):
        completed.add("音源生成")
    if _file_asset_present(assets.master_audio) or (
        _skip_manual_mastering(root) and _file_asset_present(assets.raw_master)
    ):
        completed.add("マスター化")
    if _file_asset_present(assets.master_video):
        completed.add("動画化")
    if state.thumbnail_approved:
        completed.add("サムネイル")
    if phase == "complete":
        completed.add("アップロード")

    video_id = _video_id(state)
    if _publish_followup_complete(root, collection, video_id):
        completed.add("公開後処理")
    if _analysis_complete(root, _publish_date(state)):
        completed.add("分析")
    return frozenset(completed)


def load_progress_snapshot(cwd: str | None, command: str | None) -> ProgressSnapshot | None:
    """コレクションが無い、または状態を安全に読めない場合は fallback を指示する。"""

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
