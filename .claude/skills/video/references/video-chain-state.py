#!/usr/bin/env python3
"""Return the resumable state of one video chain step as JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TypedDict

EXIT_SKIP = 0
EXIT_RUN = 10
EXIT_BLOCKED = 20
EXIT_ERROR = 2
_STEPS = ("generate",)


class StateResult(TypedDict):
    step: str
    decision: str
    reason: str
    artifacts: list[str]


def _result(step: str, decision: str, reason: str, artifacts: list[str]) -> StateResult:
    return {"step": step, "decision": decision, "reason": reason, "artifacts": artifacts}


def _master_video_from_state(collection: Path) -> object:
    state_path = collection / "workflow-state.json"
    if not state_path.is_file():
        raise ValueError(f"workflow-state.json がありません: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("workflow-state.json は object である必要があります")
    assets = state.get("assets")
    if not isinstance(assets, dict):
        raise ValueError("workflow-state.json::assets は object である必要があります")
    return assets.get("master_video")


def evaluate(collection: Path, step: str) -> tuple[int, StateResult]:
    collection = collection.resolve()
    if step not in _STEPS:
        raise ValueError(f"未知の step です: {step}")

    value = _master_video_from_state(collection)
    if value is None:
        return EXIT_RUN, _result(step, "run", "master_video_missing", [])
    if not isinstance(value, str) or not value.strip():
        return EXIT_BLOCKED, _result(step, "blocked", "master_video_value_invalid", [])

    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        return EXIT_BLOCKED, _result(step, "blocked", "master_video_path_invalid", [])
    path = collection / relative
    if not path.is_file():
        return EXIT_RUN, _result(step, "run", "master_video_file_missing", [relative.as_posix()])
    return EXIT_SKIP, _result(step, "skip", "master_video_exists", [relative.as_posix()])


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
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        code = EXIT_ERROR
        result = _result(args.step, "error", str(exc), [])
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
