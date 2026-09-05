#!/usr/bin/env python3
"""Return the resumable state of one video chain step as JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NotRequired, TypedDict

from youtube_automation.application.master_video_review import require_approved_master_video
from youtube_automation.core.errors import ReviewError, ValidationError, WorkflowStateError
from youtube_automation.domains.documents.video_description import read_video_description_metadata

EXIT_SKIP = 0
EXIT_RUN = 10
EXIT_BLOCKED = 20
EXIT_ERROR = 2
_STEPS = ("generate", "describe")


class StateResult(TypedDict):
    step: str
    decision: str
    reason: str
    artifacts: list[str]
    next: NotRequired[str]


def _result(step: str, decision: str, reason: str, artifacts: list[str]) -> StateResult:
    result: StateResult = {"step": step, "decision": decision, "reason": reason, "artifacts": artifacts}
    if step == "generate" and decision in {"run", "blocked"}:
        result["next"] = "video --generate: 動画を生成・修復し、既存動画はfull reviewで再承認してください"
    return result


def _workflow_state(collection: Path) -> dict[str, object]:
    state_path = collection / "workflow-state.json"
    if not state_path.is_file():
        raise ValueError(f"workflow-state.json がありません: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("workflow-state.json は object である必要があります")
    assets = state.get("assets")
    if not isinstance(assets, dict):
        raise ValueError("workflow-state.json::assets は object である必要があります")
    return state


def _master_video_from_state(state: dict[str, object]) -> object:
    assets = state.get("assets")
    if not isinstance(assets, dict):
        raise ValueError("workflow-state.json::assets は object である必要があります")
    return assets.get("master_video")


def _master_video_path(collection: Path, value: object) -> tuple[Path | None, StateResult | None]:
    if value is None:
        return None, _result("generate", "run", "master_video_missing", [])
    if not isinstance(value, str) or not value.strip():
        return None, _result("generate", "blocked", "master_video_value_invalid", [])
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        return None, _result("generate", "blocked", "master_video_path_invalid", [])
    if len(relative.parts) == 1:
        relative = Path("01-master") / relative
    return collection / relative, None


def evaluate(collection: Path, step: str) -> tuple[int, StateResult]:
    collection = collection.resolve()
    if step not in _STEPS:
        raise ValueError(f"未知の step です: {step}")

    state = _workflow_state(collection)
    value = _master_video_from_state(state)
    path, invalid = _master_video_path(collection, value)
    if invalid is not None:
        decision = invalid["decision"] if step == "generate" else "blocked"
        code = EXIT_RUN if decision == "run" else EXIT_BLOCKED
        return code, _result(step, decision, invalid["reason"], [])
    assert path is not None and isinstance(value, str)
    relative = path.relative_to(collection)
    if not path.is_file():
        decision = "run" if step == "generate" else "blocked"
        code = EXIT_RUN if step == "generate" else EXIT_BLOCKED
        return code, _result(step, decision, "master_video_file_missing", [relative.as_posix()])
    if step == "generate":
        try:
            require_approved_master_video(path, collection / "workflow-state.json")
        except (ReviewError, WorkflowStateError, OSError, ValueError) as exc:
            return EXIT_BLOCKED, _result(step, "blocked", str(exc), [relative.as_posix()])
        return EXIT_SKIP, _result(step, "skip", "master_video_exists", [relative.as_posix()])

    assets = state.get("assets")
    generated = isinstance(assets, dict) and assets.get("description") is True
    output = collection / "20-documentation" / "descriptions.json"
    if generated and output.is_file():
        try:
            read_video_description_metadata(output)
        except ValidationError:
            return EXIT_RUN, _result(step, "run", "description_pair_invalid", [])
        return EXIT_SKIP, _result(
            step,
            "skip",
            "description_exists",
            ["20-documentation/descriptions.json", "20-documentation/descriptions.html"],
        )
    return EXIT_RUN, _result(step, "run", "description_incomplete", [])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection-dir", type=Path, required=True)
    parser.add_argument("--step", choices=_STEPS, required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        code, result = evaluate(args.collection_dir, args.step)
    except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        code = EXIT_ERROR
        result = _result(args.step, "error", str(exc), [])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
