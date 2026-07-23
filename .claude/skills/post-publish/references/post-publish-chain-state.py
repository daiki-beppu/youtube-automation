#!/usr/bin/env python3
"""Resolve and atomically update post-publish completion state by video ID."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

EXIT_SKIP = 0
EXIT_RUN = 10
EXIT_BLOCKED = 20
EXIT_PENDING = 30
EXIT_ERROR = 2
SCHEMA_VERSION = 1
STEPS = ("community-post", "pinned-comment", "metadata-audit")
HISTORY_NAME = "post_publish_history.json"


class StateResult(TypedDict):
    step: str
    decision: str
    reason: str
    video_id: str | None
    history_file: str
    completed_steps: list[str]
    pending_until: str | None


def _read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON を読めません: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root は object でなければなりません: {path}")
    return value


def resolve_video_id(collection: Path) -> str | None:
    tracking_path = collection / "20-documentation" / "upload_tracking.json"
    if tracking_path.is_file():
        tracking = _read_object(tracking_path)
        video_id = (tracking.get("complete_collection") or {}).get("video_id")
        if isinstance(video_id, str) and video_id:
            return video_id
    state_path = collection / "workflow-state.json"
    if state_path.is_file():
        state = _read_object(state_path)
        video_id = (state.get("upload") or {}).get("video_id") or state.get("video_id")
        if isinstance(video_id, str) and video_id:
            return video_id
    return None


def resolve_publish_at(collection: Path) -> datetime | None:
    """Resolve the scheduled publish time from upload tracking, then workflow state."""
    candidates: list[object] = []
    tracking_path = collection / "20-documentation" / "upload_tracking.json"
    if tracking_path.is_file():
        tracking = _read_object(tracking_path)
        candidates.append((tracking.get("complete_collection") or {}).get("publish_at"))
    state_path = collection / "workflow-state.json"
    if state_path.is_file():
        state = _read_object(state_path)
        candidates.append((state.get("upload") or {}).get("publish_at"))
    for value in candidates:
        if not isinstance(value, str) or not value:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"publish_at が ISO 8601 ではありません: {value}") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"publish_at に timezone がありません: {value}")
        return parsed.astimezone(UTC)
    return None


def _load_history(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "videos": {}}
    history = _read_object(path)
    if history.get("schema_version") != SCHEMA_VERSION or not isinstance(history.get("videos"), dict):
        raise ValueError(f"未対応の post-publish history schema です: {path}")
    for video_id, video in history["videos"].items():
        if not isinstance(video_id, str) or not video_id or not isinstance(video, dict):
            raise ValueError(f"不正な video entry です: {path}: video_id={video_id!r}")
        completed = video.get("completed")
        if not isinstance(completed, dict):
            raise ValueError(f"completed は object でなければなりません: video_id={video_id}")
        unknown_steps = set(completed) - set(STEPS)
        if unknown_steps or any(not isinstance(value, str) or not value for value in completed.values()):
            raise ValueError(f"不正な completed entry です: video_id={video_id}")
        pending = video.get("pending", {})
        if not isinstance(pending, dict):
            raise ValueError(f"pending は object でなければなりません: video_id={video_id}")
        unknown_pending = set(pending) - {"pinned-comment"}
        if unknown_pending or any(not isinstance(value, str) or not value for value in pending.values()):
            raise ValueError(f"不正な pending entry です: video_id={video_id}")
    return history


def evaluate(
    root: Path,
    collection: Path,
    step: str,
    *,
    now: datetime | None = None,
) -> tuple[int, StateResult]:
    if step not in STEPS:
        raise ValueError(f"未知の step です: {step}")
    root = root.resolve()
    collection = collection.resolve()
    try:
        collection.relative_to(root)
    except ValueError as exc:
        raise ValueError("collection は channel-dir 配下でなければなりません") from exc
    history_path = root / HISTORY_NAME
    video_id = resolve_video_id(collection)
    if video_id is None:
        return EXIT_BLOCKED, {
            "step": step,
            "decision": "blocked",
            "reason": "video_id_missing",
            "video_id": None,
            "history_file": HISTORY_NAME,
            "completed_steps": [],
            "pending_until": None,
        }
    history = _load_history(history_path)
    video = history["videos"].get(video_id, {"completed": {}})
    completed = video["completed"]
    completed_steps = [candidate for candidate in STEPS if candidate in completed]
    if step in completed:
        return EXIT_SKIP, {
            "step": step,
            "decision": "skip",
            "reason": "already_completed",
            "video_id": video_id,
            "history_file": HISTORY_NAME,
            "completed_steps": completed_steps,
            "pending_until": None,
        }
    predecessor_index = STEPS.index(step)
    missing = [candidate for candidate in STEPS[:predecessor_index] if candidate not in completed]
    if missing:
        return EXIT_BLOCKED, {
            "step": step,
            "decision": "blocked",
            "reason": f"previous_steps_incomplete:{','.join(missing)}",
            "video_id": video_id,
            "history_file": HISTORY_NAME,
            "completed_steps": completed_steps,
            "pending_until": None,
        }
    publish_at = resolve_publish_at(collection) if step == "pinned-comment" else None
    current = datetime.now(UTC) if now is None else now.astimezone(UTC)
    if publish_at is not None and publish_at > current:
        return EXIT_PENDING, {
            "step": step,
            "decision": "pending_until_publish",
            "reason": "scheduled_publish_in_future",
            "video_id": video_id,
            "history_file": HISTORY_NAME,
            "completed_steps": completed_steps,
            "pending_until": publish_at.isoformat(),
        }
    return EXIT_RUN, {
        "step": step,
        "decision": "run",
        "reason": "not_completed",
        "video_id": video_id,
        "history_file": HISTORY_NAME,
        "completed_steps": completed_steps,
        "pending_until": None,
    }


def mark_complete(
    root: Path,
    collection: Path,
    step: str,
    *,
    now: datetime | None = None,
) -> StateResult:
    code, result = evaluate(root, collection, step, now=now)
    if code == EXIT_SKIP:
        return result
    if code != EXIT_RUN or result["video_id"] is None:
        raise ValueError(result["reason"])
    root = root.resolve()
    history_path = root / HISTORY_NAME
    history = _load_history(history_path)
    video_id = result["video_id"]
    video = history["videos"].setdefault(video_id, {"completed": {}, "pending": {}})
    completed = video.setdefault("completed", {})
    completed[step] = datetime.now(UTC).isoformat()
    video.setdefault("pending", {}).pop(step, None)
    temp_path = history_path.with_name(f".{history_path.name}.{os.getpid()}.tmp")
    try:
        temp_path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp_path, history_path)
    finally:
        temp_path.unlink(missing_ok=True)
    _, updated = evaluate(root, collection, step)
    return updated


def mark_pending_until_publish(
    root: Path,
    collection: Path,
    step: str,
    *,
    now: datetime | None = None,
) -> StateResult:
    code, result = evaluate(root, collection, step, now=now)
    if code != EXIT_PENDING or result["video_id"] is None or result["pending_until"] is None:
        raise ValueError(result["reason"])
    history_path = root.resolve() / HISTORY_NAME
    history = _load_history(history_path)
    video = history["videos"].setdefault(result["video_id"], {"completed": {}, "pending": {}})
    video.setdefault("pending", {})[step] = result["pending_until"]
    temp_path = history_path.with_name(f".{history_path.name}.{os.getpid()}.tmp")
    try:
        temp_path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp_path, history_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel-dir", type=Path, required=True)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--step", choices=STEPS, required=True)
    parser.add_argument("--mark-complete", action="store_true")
    parser.add_argument("--mark-pending-until-publish", action="store_true")
    args = parser.parse_args()
    root = args.channel_dir.resolve()
    collection = args.collection if args.collection.is_absolute() else root / args.collection
    try:
        if args.mark_complete and args.mark_pending_until_publish:
            raise ValueError("mark action は同時指定できません")
        if args.mark_complete:
            result = mark_complete(root, collection, args.step)
            code = EXIT_SKIP
        elif args.mark_pending_until_publish:
            result = mark_pending_until_publish(root, collection, args.step)
            code = EXIT_PENDING
        else:
            code, result = evaluate(root, collection, args.step)
    except ValueError as exc:
        print(json.dumps({"step": args.step, "decision": "error", "reason": str(exc)}, ensure_ascii=False))
        return EXIT_ERROR
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
