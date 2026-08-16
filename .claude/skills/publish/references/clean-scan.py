#!/usr/bin/env python3
"""Pull Git control state, then classify live collections for safe cleanup."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, TypedDict

from youtube_automation.core.errors import AutomationError, StateSyncError, WorkflowStateError
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.infrastructure.vcs.state_git import build_pull_context
from youtube_automation.infrastructure.vcs.state_sync import pull_then_read

EXIT_READY = 0
EXIT_BLOCKED = 20


class CleanupDecision(NamedTuple):
    eligible: bool
    reason: str | None


class CollectionDecision(TypedDict):
    collection: str
    reason: str


class EligibleCollection(TypedDict):
    collection: str
    video_id: str


class CleanScanReport(TypedDict):
    eligible: list[EligibleCollection]
    skipped: list[CollectionDecision]


def _publish_at_elapsed(value: str, now: datetime) -> CleanupDecision:
    try:
        publish_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return CleanupDecision(False, "publish_at_invalid")
    if publish_at.tzinfo is None:
        return CleanupDecision(False, "publish_at_invalid")
    if publish_at > now:
        return CleanupDecision(False, "publish_at_not_elapsed")
    return CleanupDecision(True, None)


def evaluate(state: WorkflowState, now: datetime) -> CleanupDecision:
    """Evaluate the existing three gates plus elapsed ``upload.publish_at``."""
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    try:
        if state.stage != "live":
            return CleanupDecision(False, "stage_not_live")
        if state.phase != "complete":
            return CleanupDecision(False, "phase_not_complete")
        upload = state.upload
        if upload is None or not (upload.video_id or "").strip():
            return CleanupDecision(False, "video_id_missing")
        publish_at = upload.publish_at
    except WorkflowStateError:
        return CleanupDecision(False, "workflow_state_invalid")
    if publish_at is None:
        return CleanupDecision(True, None)
    return _publish_at_elapsed(publish_at, now)


def scan(channel_dir: Path, now: datetime) -> CleanScanReport:
    live_dir = channel_dir / "collections" / "live"
    eligible: list[EligibleCollection] = []
    skipped: list[CollectionDecision] = []
    if live_dir.is_symlink():
        raise StateSyncError(f"collections/live must not be a symlink: {live_dir}")
    if not live_dir.is_dir():
        return {"eligible": eligible, "skipped": skipped}

    for collection in sorted(live_dir.iterdir(), key=lambda path: path.name):
        if collection.is_symlink() or not collection.is_dir():
            continue
        state_path = collection / "workflow-state.json"
        if not state_path.exists() and not state_path.is_symlink():
            continue
        try:
            state = read_workflow_state(state_path)
        except WorkflowStateError:
            skipped.append({"collection": collection.name, "reason": "workflow_state_invalid"})
            continue
        decision = evaluate(state, now)
        if decision.eligible:
            upload = state.upload
            assert upload is not None
            video_id = upload.video_id
            assert video_id is not None
            eligible.append({"collection": collection.name, "video_id": video_id})
        else:
            assert decision.reason is not None
            skipped.append({"collection": collection.name, "reason": decision.reason})
    return {"eligible": eligible, "skipped": skipped}


def pull_and_scan(channel_dir: Path, now: datetime) -> CleanScanReport:
    """Run classification only after the Git state pull gate succeeds."""
    context = build_pull_context(channel_dir)
    return pull_then_read(context, lambda: scan(context.channel_dir, now))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="pull済みGit stateからpublish clean対象を分類します")
    parser.add_argument("--channel-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = pull_and_scan(args.channel_dir, datetime.now(timezone.utc))
    except StateSyncError as exc:
        print(f"publish clean blocked: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    except AutomationError as exc:
        print(f"publish clean preflight failed: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return EXIT_READY


if __name__ == "__main__":
    raise SystemExit(main())
