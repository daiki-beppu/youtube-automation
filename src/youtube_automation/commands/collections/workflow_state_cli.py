"""workflow-state.json の制御面を安全に読み書きする CLI。"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.domains.collections.workflow_state import Phase, Stage, WorkflowState
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.domains.collections.workflow_state import update as update_workflow_state
from youtube_automation.infrastructure.filesystem import JSONValue
from youtube_automation.infrastructure.media.collection_paths import resolve_collection_dir

_PHASE_CHOICES: tuple[Phase, ...] = ("planning", "prepared", "mastered", "publishing", "complete")
_STAGE_CHOICES: tuple[Stage, ...] = ("planning", "live")


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
    elif args.command == "touch":
        update_workflow_state(state_path, _touch)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
