"""下流チャンネルの正規状態から進捗図の完了段を解決する。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

STAGES = ("企画", "音源生成", "マスター化", "動画化", "サムネイル", "アップロード", "公開後処理", "分析")

# /wf-status が定義する v2 phase 語彙を正規の段判定にも使う。
WF_STATUS_PHASES = frozenset({"planning", "prepared", "mastered", "publishing", "complete"})
_POST_PUBLISH_STEPS = frozenset({"community-post", "pinned-comment", "metadata-audit"})
_ANALYSIS_REPORT = re.compile(r"analysis_(\d{8})\.md\Z")


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


def _state_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for location in ("planning", "live"):
        base = root / "collections" / location
        if base.is_dir():
            paths.extend(path for path in base.glob("*/workflow-state.json") if path.is_file())
    return paths


def _select_state(paths: list[Path], command: str | None) -> Path | None:
    if not paths:
        return None
    if command is not None:
        named = [path for path in paths if path.parent.name in command]
        if named:
            return max(named, key=lambda path: len(path.parent.name))
    return max(paths, key=lambda path: path.stat().st_mtime_ns)


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


def _thumbnail_present(value: object) -> bool:
    return value is True or _file_asset_present(value)


def _video_id(state: Mapping[object, object]) -> str | None:
    upload = state.get("upload", {})
    if not isinstance(upload, Mapping):
        return None
    value = upload.get("video_id")
    return value if isinstance(value, str) and value else None


def _post_publish_complete(root: Path, video_id: str | None) -> bool:
    if video_id is None:
        return False
    path = root / "post_publish_history.json"
    if not path.is_file():
        return False
    history = _read_object(path)
    videos = history.get("videos")
    if not isinstance(videos, Mapping):
        return False
    video = videos.get(video_id)
    if not isinstance(video, Mapping):
        return False
    completed = video.get("completed")
    return (
        isinstance(completed, Mapping)
        and _POST_PUBLISH_STEPS.issubset(completed)
        and all(isinstance(completed[step], str) and completed[step] for step in _POST_PUBLISH_STEPS)
    )


def _publish_date(state: Mapping[object, object]) -> date | None:
    upload = state.get("upload", {})
    if not isinstance(upload, Mapping):
        return None
    value = upload.get("publish_at")
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _analysis_complete(root: Path, published_on: date | None) -> bool:
    if published_on is None:
        return False
    reports = root / "reports"
    if not reports.is_dir():
        return False
    for path in reports.glob("analysis_*.md"):
        match = _ANALYSIS_REPORT.fullmatch(path.name)
        if path.is_file() and match is not None:
            try:
                report_date = datetime.strptime(match.group(1), "%Y%m%d").date()
            except ValueError:
                continue
            if report_date >= published_on:
                return True
    return False


def _completed_stages(root: Path, state: Mapping[object, object]) -> frozenset[str]:
    phase = state.get("phase")
    if phase not in WF_STATUS_PHASES:
        raise ValueError(f"unsupported workflow phase: {phase!r}")
    assets = state.get("assets")
    if not isinstance(assets, Mapping):
        raise ValueError("assets must be an object")

    completed: set[str] = set()
    if phase != "planning":
        completed.add("企画")
    if _file_asset_present(assets.get("raw_master")):
        completed.add("音源生成")
    if _file_asset_present(assets.get("master_audio")) or (
        _skip_manual_mastering(root) and _file_asset_present(assets.get("raw_master"))
    ):
        completed.add("マスター化")
    if _file_asset_present(assets.get("video")) or _file_asset_present(assets.get("master_video")):
        completed.add("動画化")
    if _thumbnail_present(assets.get("thumbnail")):
        completed.add("サムネイル")
    if phase == "complete":
        completed.add("アップロード")

    video_id = _video_id(state)
    if _post_publish_complete(root, video_id):
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
        state_path = _select_state(_state_paths(root), command)
        if state_path is None:
            return None
        state = _read_object(state_path)
        return ProgressSnapshot(_completed_stages(root, state))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
