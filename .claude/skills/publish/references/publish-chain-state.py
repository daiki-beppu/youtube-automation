#!/usr/bin/env python3
"""Decide whether publish playlist and upload steps must run."""

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


def _evaluate_playlist(channel_dir: Path) -> tuple[int, StateResult]:
    config_path = channel_dir / "config" / "channel" / "playlists.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return EXIT_BLOCKED, _result("blocked", "playlists_config_missing")
    except (OSError, json.JSONDecodeError):
        return EXIT_BLOCKED, _result("blocked", "playlists_config_invalid")
    if not isinstance(config, dict):
        return EXIT_BLOCKED, _result("blocked", "playlists_config_invalid")
    playlists = config.get("playlists")
    if not isinstance(playlists, dict) or not playlists:
        return EXIT_BLOCKED, _result("blocked", "playlists_invalid")

    for value in playlists.values():
        if isinstance(value, str):
            if not value.strip():
                return EXIT_RUN, _result("run", "playlist_id_missing")
            continue
        if not isinstance(value, dict):
            return EXIT_BLOCKED, _result("blocked", "playlist_entry_invalid")
        playlist_id = value.get("playlist_id")
        if playlist_id is None:
            return EXIT_RUN, _result("run", "playlist_id_missing")
        if not isinstance(playlist_id, str) or not playlist_id.strip():
            return EXIT_BLOCKED, _result("blocked", "playlist_id_invalid")

    return EXIT_SKIP, _result(
        "skip",
        "playlist_ids_recorded",
        artifacts=["config/channel/playlists.json::playlists.*.playlist_id"],
    )


def evaluate(
    collection_dir: Path | None,
    step: str,
    channel_dir: Path | None = None,
) -> tuple[int, StateResult]:
    """Return a stable exit code and JSON-serializable decision."""
    if step == "playlist":
        return _evaluate_playlist(channel_dir or Path.cwd())
    if step != "upload":
        return EXIT_BLOCKED, _result("blocked", "unknown_step")
    if collection_dir is None:
        return EXIT_BLOCKED, _result("blocked", "collection_dir_missing")

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
    parser.add_argument("--collection-dir", type=Path)
    parser.add_argument("--channel-dir", type=Path, default=Path.cwd())
    parser.add_argument("--step", required=True)
    args = parser.parse_args()
    code, result = evaluate(args.collection_dir, args.step, args.channel_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
