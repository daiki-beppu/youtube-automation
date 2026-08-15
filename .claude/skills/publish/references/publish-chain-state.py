#!/usr/bin/env python3
"""Decide whether the publish upload step must run for a collection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import NotRequired, TypedDict

EXIT_SKIP = 0
EXIT_RUN = 10
EXIT_BLOCKED = 20


class StateResult(TypedDict):
    decision: str
    reason: str
    artifacts: NotRequired[list[str]]


def _result(decision: str, reason: str, *, artifacts: list[str] | None = None) -> StateResult:
    result: StateResult = {"decision": decision, "reason": reason}
    if artifacts is not None:
        result["artifacts"] = artifacts
    return result


def evaluate(collection_dir: Path, step: str) -> tuple[int, StateResult]:
    """Return a stable exit code and JSON-serializable decision."""
    if step != "upload":
        return EXIT_BLOCKED, _result("blocked", "unknown_step")

    state_path = collection_dir / "workflow-state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return EXIT_RUN, _result("run", "workflow_state_missing")
    except (OSError, json.JSONDecodeError):
        return EXIT_BLOCKED, _result("blocked", "workflow_state_invalid")

    if not isinstance(state, dict):
        return EXIT_BLOCKED, _result("blocked", "workflow_state_invalid")
    upload = state.get("upload")
    if upload is None:
        return EXIT_RUN, _result("run", "video_id_missing")
    if not isinstance(upload, dict):
        return EXIT_BLOCKED, _result("blocked", "upload_state_invalid")

    video_id = upload.get("video_id")
    if video_id is None:
        return EXIT_RUN, _result("run", "video_id_missing")
    if not isinstance(video_id, str) or not video_id.strip():
        return EXIT_BLOCKED, _result("blocked", "video_id_invalid")
    return EXIT_SKIP, _result(
        "skip",
        "video_id_recorded",
        artifacts=["workflow-state.json::upload.video_id"],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection-dir", required=True, type=Path)
    parser.add_argument("--step", required=True)
    args = parser.parse_args()
    code, result = evaluate(args.collection_dir, args.step)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
