"""workflow-state.json の制御面を安全に読み書きする CLI。"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.core.errors import WorkflowStateError
from youtube_automation.domains.collections.workflow_state import AssetKey, Phase, PlanningKey, Stage, WorkflowState
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.domains.collections.workflow_state import update as update_workflow_state
from youtube_automation.infrastructure.filesystem import JSONValue
from youtube_automation.infrastructure.media.collection_paths import resolve_collection_dir

_PHASE_CHOICES: tuple[Phase, ...] = ("planning", "prepared", "mastered", "publishing", "complete")
_STAGE_CHOICES: tuple[Stage, ...] = ("planning", "live")
_ASSET_CHOICES: tuple[AssetKey, ...] = (
    "thumbnail",
    "loop_video",
    "music_prompts",
    "music_downloaded",
    "raw_master",
    "master_audio",
    "master_video",
    "description",
)
_PLANNING_CHOICES: tuple[PlanningKey, ...] = (
    "generated",
    "final_title",
    "target_persona",
    "publish_target_at",
    "music",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="workflow-state.json の制御面を安全に読み書きします")
    parser.add_argument(
        "--collection",
        help="コレクションディレクトリ（省略時は現在のコレクションディレクトリ）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    get_parser = subparsers.add_parser("get", help="dot 区切り key path の JSON 値を表示")
    get_parser.add_argument("keypath", help="例: upload.video_id")

    phase_parser = subparsers.add_parser("set-phase", help="制作 phase を更新")
    phase_parser.add_argument("phase", choices=_PHASE_CHOICES)

    stage_parser = subparsers.add_parser("set-stage", help="collection stage を更新")
    stage_parser.add_argument("stage", choices=_STAGE_CHOICES)

    upload_parser = subparsers.add_parser("set-upload", help="YouTube upload 状態を更新")
    upload_parser.add_argument("--video-id", required=True)
    upload_parser.add_argument("--video-url")
    upload_parser.add_argument("--publish-at")
    asset_parser = subparsers.add_parser("set-asset", help="生成 asset の JSON 値を更新")
    asset_parser.add_argument("key", choices=_ASSET_CHOICES)
    asset_parser.add_argument("value", help="JSON 値（文字列は JSON の二重引用符を含める）")
    planning_parser = subparsers.add_parser("set-planning", help="planning の JSON 値を更新")
    planning_parser.add_argument("key", choices=_PLANNING_CHOICES)
    planning_parser.add_argument("value", help="JSON 値（文字列は JSON の二重引用符を含める）")
    for command, help_text in (
        ("set-thumbnail-approved", "thumbnail 承認状態を更新"),
        ("set-description-generated", "概要欄生成状態を更新"),
    ):
        bool_parser = subparsers.add_parser(command, help=help_text)
        bool_parser.add_argument("value", choices=("true", "false"))
    shorts_parser = subparsers.add_parser("set-post-upload-shorts", help="shorts 公開記録を JSON 配列で更新")
    shorts_parser.add_argument("value", help="short record の JSON 配列")
    subparsers.add_parser("touch", help="updated_at を現在時刻へ更新")
    return parser


def _state_path(collection: str | None) -> Path:
    return resolve_collection_dir(collection) / "workflow-state.json"


def _get_keypath(document: Mapping[str, JSONValue], keypath: str) -> JSONValue:
    current: JSONValue = dict(document)
    for segment in keypath.split("."):
        if not segment or not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _set_upload(state: WorkflowState, args: argparse.Namespace) -> None:
    if state.upload is None:
        state["upload"] = {}
    upload = state.upload
    assert upload is not None
    upload.video_id = args.video_id
    if args.video_url is not None:
        upload.video_url = args.video_url
    if args.publish_at is not None:
        upload.publish_at = args.publish_at
    _touch(state)


def _touch(state: WorkflowState) -> None:
    state["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _set_phase(state: WorkflowState, phase: Phase) -> None:
    state.phase = phase
    _touch(state)


def _set_stage(state: WorkflowState, stage: Stage) -> None:
    state.stage = stage
    _touch(state)


def _json_value(raw: str) -> JSONValue:
    try:
        return cast(JSONValue, json.loads(raw))
    except json.JSONDecodeError as exc:
        raise WorkflowStateError(f"value must be valid JSON: {exc.msg}") from exc


def _set_asset(state: WorkflowState, key: AssetKey, value: JSONValue) -> None:
    if state.assets is None:
        state["assets"] = {}
    assets = state.assets
    assert assets is not None
    assets.set_known(key, value)
    _touch(state)


def _set_planning(state: WorkflowState, key: PlanningKey, value: JSONValue) -> None:
    if state.planning is None:
        state["planning"] = {}
    planning = state.planning
    assert planning is not None
    planning.set_known(key, value)
    _touch(state)


def _set_post_upload_shorts(state: WorkflowState, value: JSONValue) -> None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise WorkflowStateError("workflow-state.json::post_upload.shorts must be an array of objects")
    if state.post_upload is None:
        state["post_upload"] = {}
    post_upload = state.post_upload
    assert post_upload is not None
    post_upload.shorts = cast(list[dict[str, JSONValue]], value)
    _touch(state)


def _set_completion_flag(
    state: WorkflowState,
    *,
    thumbnail: bool | None = None,
    description: bool | None = None,
) -> None:
    if thumbnail is not None:
        state.set_thumbnail_approved(thumbnail)
    if description is not None:
        state.set_description_generated(description)
    _touch(state)


def run(args: argparse.Namespace) -> int:
    state_path = _state_path(args.collection)
    if args.command == "get":
        value = _get_keypath(read_workflow_state(state_path).to_dict(), args.keypath)
        print(json.dumps(value, ensure_ascii=False))
    elif args.command == "set-phase":
        phase = cast(Phase, args.phase)
        update_workflow_state(state_path, lambda state: _set_phase(state, phase))
    elif args.command == "set-stage":
        stage = cast(Stage, args.stage)
        update_workflow_state(state_path, lambda state: _set_stage(state, stage))
    elif args.command == "set-upload":
        update_workflow_state(state_path, lambda state: _set_upload(state, args))
    elif args.command == "set-asset":
        key = cast(AssetKey, args.key)
        update_workflow_state(state_path, lambda state: _set_asset(state, key, _json_value(args.value)))
    elif args.command == "set-planning":
        key = cast(PlanningKey, args.key)
        update_workflow_state(state_path, lambda state: _set_planning(state, key, _json_value(args.value)))
    elif args.command == "set-thumbnail-approved":
        update_workflow_state(state_path, lambda state: _set_completion_flag(state, thumbnail=args.value == "true"))
    elif args.command == "set-description-generated":
        update_workflow_state(state_path, lambda state: _set_completion_flag(state, description=args.value == "true"))
    elif args.command == "set-post-upload-shorts":
        update_workflow_state(state_path, lambda state: _set_post_upload_shorts(state, _json_value(args.value)))
    elif args.command == "touch":
        update_workflow_state(state_path, _touch)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
