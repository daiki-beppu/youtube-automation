#!/usr/bin/env python3
"""Resolve canonical `/wf-new --auto` actions and maintain its lease/history state."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import secrets
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict

from youtube_automation.core.errors import StateSyncError, ValidationError, WorkflowStateError
from youtube_automation.domains.collections.workflow_state import WorkflowState
from youtube_automation.domains.collections.workflow_state import read as read_workflow_state
from youtube_automation.domains.documents.video_description import read_video_description_metadata
from youtube_automation.domains.post_publish import verify_post_publish_completion

STATE_DIR_NAME = ".automation-run"
LEASE_DIR_NAME = "lease"
LEASE_FILE_NAME = "lease.json"
LEASE_MUTEX_NAME = "lease.mutex"
HISTORY_FILE_NAME = "history.json"
AUDIO_SUFFIXES = {".mp3", ".m4a", ".wav", ".flac", ".aac"}
PHASES = {"planning", "prepared", "cloud_owned", "mastered", "publishing", "complete"}
ENGINES = {"suno", "lyria", "minimax"}
ACTIONS = {
    "wf-new",
    "lyria",
    "minimax",
    "suno-helper",
    "masterup",
    "wf-next-local",
    "wf-next",
    "publish",
    "post-publish",
    "blocked",
    "complete",
    "no-op",
}


class LeaseBusyError(RuntimeError):
    """Raised when another non-expired integrated run owns the lease."""


class NoActiveCollectionError(ValueError):
    """Raised when no unfinished planning collection can be selected."""


@dataclass(frozen=True)
class RunnerConfig:
    allow_external_publish: bool
    post_publish_configured: bool
    skip_audio_approval: bool = True
    skip_upload_approval: bool = True


class Decision(TypedDict):
    collection: str | None
    phase: str
    engine: str | None
    action: str
    reason: str
    resume_action: str | None
    allow_external_publish: bool


class TimingSegment(TypedDict):
    kind: Literal["ai", "human"]
    started_at: str
    ended_at: str
    duration_seconds: float


def _read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON を読めません: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root は object でなければなりません: {path}")
    return value


def read_history(root: Path) -> dict:
    """Read workflow attempts without inventing timing for schema v1 data."""
    history_path = root.resolve() / STATE_DIR_NAME / HISTORY_FILE_NAME
    if history_path.is_symlink():
        raise ValueError(f"history に symlink は使えません: {history_path}")
    if not history_path.exists():
        return {"schema_version": 1, "attempts": []}

    history = _read_object(history_path)
    attempts = history.get("attempts")
    schema_version = history.get("schema_version")
    if schema_version not in {1, 2} or not isinstance(attempts, list):
        raise ValueError(f"未対応 .automation-run history です: {history_path}")

    normalized_attempts = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise ValueError(f"history attempt は object でなければなりません: {history_path}")
        normalized = {**attempt, "timing": None} if schema_version == 1 else {**attempt}
        if schema_version == 2:
            _validate_timing(normalized.get("timing"), source=str(history_path))
        normalized_attempts.append(normalized)
    return {**history, "attempts": normalized_attempts}


def _timestamp(value: object, *, field: str, source: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{source}: {field} は ISO 8601 文字列でなければなりません")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{source}: {field} は ISO 8601 でなければなりません: {value}") from exc


def _validate_timing(timing: object, *, source: str) -> None:
    if timing is None:
        return
    if not isinstance(timing, dict) or not isinstance(timing.get("segments"), list):
        raise ValueError(f"{source}: timing.segments は array でなければなりません")
    for index, segment in enumerate(timing["segments"]):
        prefix = f"timing.segments[{index}]"
        if not isinstance(segment, dict):
            raise ValueError(f"{source}: {prefix} は object でなければなりません")
        if segment.get("kind") not in {"ai", "human"}:
            raise ValueError(f"{source}: {prefix}.kind は ai または human でなければなりません")
        started_at = _timestamp(segment.get("started_at"), field=f"{prefix}.started_at", source=source)
        if "ended_at" not in segment:
            raise ValueError(f"{source}: {prefix} は open segment のまま保存できません")
        ended_at = _timestamp(segment["ended_at"], field=f"{prefix}.ended_at", source=source)
        try:
            reversed_time = ended_at < started_at
        except TypeError as exc:
            raise ValueError(f"{source}: {prefix} の timezone 指定が一致しません") from exc
        if reversed_time:
            raise ValueError(f"{source}: {prefix} の ended_at は started_at より前にできません")
        duration = segment.get("duration_seconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise ValueError(f"{source}: {prefix}.duration_seconds は 0 以上の有限数値でなければなりません")
        try:
            invalid_duration = duration < 0 or not math.isfinite(duration)
        except OverflowError:
            invalid_duration = True
        if invalid_duration:
            raise ValueError(f"{source}: {prefix}.duration_seconds は 0 以上の有限数値でなければなりません")


def _attempt_timing(segments: list[TimingSegment] | None) -> dict | None:
    if not segments:
        return None
    copied_segments = [{**segment} for segment in segments]
    _validate_timing({"segments": copied_segments}, source="record_attempt")
    timing = {
        "started_at": copied_segments[0]["started_at"],
        "ended_at": copied_segments[-1]["ended_at"],
        "ai_seconds": sum(segment["duration_seconds"] for segment in copied_segments if segment["kind"] == "ai"),
        "human_seconds": sum(segment["duration_seconds"] for segment in copied_segments if segment["kind"] == "human"),
        "segments": copied_segments,
    }
    return timing


def summarize_attempt_durations(history: dict) -> dict:
    """Aggregate every measured attempt without treating unavailable timing as zero."""
    if not isinstance(history, dict) or not isinstance(history.get("attempts"), list):
        raise ValueError("history は attempts array を持つ object でなければなりません")
    schema_version = history.get("schema_version")
    if schema_version == 1:
        return {
            "available": False,
            "reason": "history_schema_v1",
            "actions": None,
            "totals": None,
        }
    if schema_version != 2:
        raise ValueError(f"未対応 history schema です: {schema_version!r}")

    accumulators: dict[str, dict] = {}
    for index, attempt in enumerate(history["attempts"]):
        if not isinstance(attempt, dict):
            raise ValueError(f"history.attempts[{index}] は object でなければなりません")
        action = attempt.get("action")
        if not isinstance(action, str) or not action:
            raise ValueError(f"history.attempts[{index}].action は空でない string でなければなりません")
        collection = attempt.get("collection")
        if collection is not None and (not isinstance(collection, str) or not collection):
            raise ValueError(f"history.attempts[{index}].collection は null または空でない string です")
        timing = attempt.get("timing")
        if timing is None:
            return {
                "available": False,
                "reason": "attempt_timing_unavailable",
                "actions": None,
                "totals": None,
            }
        _validate_timing(timing, source=f"history.attempts[{index}]")

        accumulator = accumulators.setdefault(
            action,
            {
                "ai_durations": [],
                "human_durations": [],
                "attempt_count": 0,
                "work_items": set(),
            },
        )
        for segment in timing["segments"]:
            accumulator[f"{segment['kind']}_durations"].append(float(segment["duration_seconds"]))
        accumulator["attempt_count"] += 1
        accumulator["work_items"].add(collection)

    actions = {}
    for action in sorted(accumulators):
        accumulator = accumulators[action]
        actions[action] = {
            "ai_seconds": math.fsum(accumulator["ai_durations"]),
            "human_seconds": math.fsum(accumulator["human_durations"]),
            "attempt_count": accumulator["attempt_count"],
            "work_item_count": len(accumulator["work_items"]),
        }
    totals = {
        "ai_seconds": math.fsum(item["ai_seconds"] for item in actions.values()),
        "human_seconds": math.fsum(item["human_seconds"] for item in actions.values()),
        "attempt_count": sum(item["attempt_count"] for item in actions.values()),
        "work_item_count": sum(item["work_item_count"] for item in actions.values()),
    }
    return {"available": True, "reason": None, "actions": actions, "totals": totals}


def summarize_time_savings(history: dict, manual_baseline_minutes: dict[str, float] | None) -> dict:
    """Apply configured per-work-item baselines to measured attempt durations."""
    duration_summary = summarize_attempt_durations(history)
    if not duration_summary["available"]:
        return duration_summary
    if manual_baseline_minutes is None:
        return {
            "available": False,
            "reason": "manual_baseline_unconfigured",
            "actions": None,
            "totals": None,
        }
    if not isinstance(manual_baseline_minutes, dict):
        raise ValueError("manual_baseline_minutes は object または null でなければなりません")

    actions = {}
    for action, duration in duration_summary["actions"].items():
        if action not in manual_baseline_minutes:
            return {
                "available": False,
                "reason": f"manual_baseline_missing:{action}",
                "actions": None,
                "totals": None,
            }
        minutes = manual_baseline_minutes[action]
        if isinstance(minutes, bool) or not isinstance(minutes, (int, float)):
            raise ValueError(f"manual_baseline_minutes.{action} は 0 以上の有限 number でなければなりません")
        try:
            invalid_minutes = minutes < 0 or not math.isfinite(minutes)
        except OverflowError:
            invalid_minutes = True
        if invalid_minutes:
            raise ValueError(f"manual_baseline_minutes.{action} は 0 以上の有限 number でなければなりません")

        baseline_seconds = float(minutes) * 60 * duration["work_item_count"]
        actions[action] = {
            **duration,
            "manual_baseline_seconds": baseline_seconds,
            "ai_inclusive_saved_seconds": max(
                0.0,
                baseline_seconds - duration["ai_seconds"] - duration["human_seconds"],
            ),
            "human_freed_seconds": max(0.0, baseline_seconds - duration["human_seconds"]),
        }

    duration_totals = duration_summary["totals"]
    baseline_total = math.fsum(item["manual_baseline_seconds"] for item in actions.values())
    totals = {
        **duration_totals,
        "manual_baseline_seconds": baseline_total,
        "ai_inclusive_saved_seconds": max(
            0.0,
            baseline_total - duration_totals["ai_seconds"] - duration_totals["human_seconds"],
        ),
        "human_freed_seconds": max(0.0, baseline_total - duration_totals["human_seconds"]),
    }
    return {"available": True, "reason": None, "actions": actions, "totals": totals}


def _ai_timing_segment(started_at: str, ended_at: str) -> TimingSegment:
    started = _timestamp(started_at, field="ai_started_at", source="record")
    ended = _timestamp(ended_at, field="recorded_at", source="record")
    try:
        duration_seconds = (ended - started).total_seconds()
    except TypeError as exc:
        raise ValueError("record: ai_started_at と recorded_at の timezone 指定が一致しません") from exc
    segment: TimingSegment = {
        "kind": "ai",
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": duration_seconds,
    }
    _validate_timing({"segments": [segment]}, source="record")
    return segment


def _timing_segment(kind: Literal["ai", "human"], started_at: str, ended_at: str) -> TimingSegment:
    started = _timestamp(started_at, field=f"{kind}_started_at", source="record")
    ended = _timestamp(ended_at, field=f"{kind}_ended_at", source="record")
    try:
        duration_seconds = (ended - started).total_seconds()
    except TypeError as exc:
        raise ValueError("record: timing boundary の timezone 指定が一致しません") from exc
    segment: TimingSegment = {
        "kind": kind,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": duration_seconds,
    }
    _validate_timing({"segments": [segment]}, source="record")
    return segment


def _human_interval(interval: list[str], index: int) -> tuple[str, str, datetime, datetime]:
    human_started_text, human_ended_text = interval
    human_started = _timestamp(
        human_started_text,
        field=f"human_intervals[{index}].started_at",
        source="record",
    )
    human_ended = _timestamp(
        human_ended_text,
        field=f"human_intervals[{index}].ended_at",
        source="record",
    )
    try:
        if human_ended < human_started:
            raise ValueError(f"record: human_intervals[{index}].ended_at は started_at より前にできません")
    except TypeError as exc:
        raise ValueError("record: timing boundary の timezone 指定が一致しません") from exc
    return human_started_text, human_ended_text, human_started, human_ended


def _timing_segments(
    ai_started_at: str,
    human_intervals: list[list[str]],
    recorded_at: str,
) -> list[TimingSegment]:
    ai_started = _timestamp(ai_started_at, field="ai_started_at", source="record")
    recorded = _timestamp(recorded_at, field="recorded_at", source="record")
    cursor_at = ai_started
    cursor_text = ai_started_at
    segments: list[TimingSegment] = []
    try:
        if recorded < ai_started:
            raise ValueError("record: recorded_at は ai_started_at より前にできません")
        for index, interval in enumerate(human_intervals):
            human_started_text, human_ended_text, human_started, human_ended = _human_interval(interval, index)
            if human_started < ai_started:
                raise ValueError(f"record: human_intervals[{index}] は ai_started_at より前にできません")
            if human_started < cursor_at:
                raise ValueError(f"record: human_intervals[{index}] は直前の区間と overlap しています")
            if human_ended > recorded:
                raise ValueError(f"record: human_intervals[{index}] は recorded_at より後にできません")
            if cursor_at < human_started:
                segments.append(_timing_segment("ai", cursor_text, human_started_text))
            segments.append(_timing_segment("human", human_started_text, human_ended_text))
            cursor_at = human_ended
            cursor_text = human_ended_text
    except TypeError as exc:
        raise ValueError("record: timing boundary の timezone 指定が一致しません") from exc
    if cursor_at < recorded:
        segments.append(_timing_segment("ai", cursor_text, recorded_at))
    return segments


def _inside(root: Path, path: Path, field: str) -> Path:
    root = root.resolve()
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} は channel-dir 配下でなければなりません") from exc
    return path


def _state(collection: Path) -> WorkflowState:
    state_path = collection / "workflow-state.json"
    if state_path.is_symlink() or not state_path.is_file():
        raise ValueError(f"workflow-state.json は通常ファイルでなければなりません: {state_path}")
    try:
        state = read_workflow_state(state_path)
    except WorkflowStateError as exc:
        cause = exc.__cause__
        if isinstance(cause, (OSError, json.JSONDecodeError)):
            raise ValueError(f"JSON を読めません: {state_path}: {cause}") from exc
        if "root must be an object" in str(exc):
            raise ValueError(f"JSON root は object でなければなりません: {state_path}") from exc
        raise ValueError(str(exc)) from exc
    try:
        phase = state.phase
    except WorkflowStateError as exc:
        raw_phase = state.get("phase")
        raise ValueError(f"未対応 phase です: {raw_phase!r}") from exc
    if phase not in PHASES:
        raise ValueError(f"未対応 phase です: {phase!r}")
    return state


def _engine(state: WorkflowState) -> str:
    try:
        engine = state.music_engine
    except WorkflowStateError as exc:
        raise ValueError(str(exc)) from exc
    if engine not in ENGINES:
        raise ValueError(f"未対応 music engine です: {engine!r}")
    return engine


def _collection_sort_key(collection: Path) -> tuple[str, str]:
    state = _state(collection)
    try:
        created_at = state.created_at
    except WorkflowStateError as exc:
        raise ValueError(str(exc)) from exc
    return (created_at or "9999", collection.name)


def select_collection(root: Path, requested: str | None = None) -> Path:
    root = root.resolve()
    if requested:
        candidate = Path(requested)
        if candidate.is_absolute():
            collection = _inside(root, candidate, "collection")
            _state(collection)
            return collection
        for stage in ("planning", "live"):
            collection = root / "collections" / stage / requested
            if collection.is_dir():
                _state(collection)
                return collection.resolve()
        raise ValueError(f"collection が見つかりません: {requested}")

    planning_root = root / "collections" / "planning"
    candidates = []
    if planning_root.is_dir():
        for state_path in planning_root.glob("*/workflow-state.json"):
            collection = state_path.parent
            if _state(collection).phase != "complete":
                candidates.append(collection.resolve())
    if not candidates:
        raise NoActiveCollectionError("未完了の planning collection がありません")
    return min(candidates, key=_collection_sort_key)


def _decision(
    *,
    collection: Path,
    phase: str,
    engine: str,
    action: str,
    reason: str,
    config: RunnerConfig,
    resume_action: str | None = None,
) -> Decision:
    return {
        "collection": collection.as_posix(),
        "phase": phase,
        "engine": engine,
        "action": action,
        "reason": reason,
        "resume_action": resume_action,
        "allow_external_publish": config.allow_external_publish,
    }


def _confined_path(root: Path, path: Path, field: str) -> Path:
    root = root.resolve()
    try:
        relative = path.absolute().relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} は許可された directory 配下でなければなりません") from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{field} の path component に symlink は使えません: {current}")
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} は許可された directory 配下でなければなりません") from exc
    return resolved


def _artifact_file(collection: Path, directory: str, value: object) -> bool:
    if not isinstance(value, str) or not value or Path(value).name != value:
        return False
    parent = collection / directory
    try:
        parent = _confined_path(collection, parent, directory)
        path = _confined_path(collection, parent / value, value)
    except ValueError:
        return False
    return path.is_file()


def _suno_download_complete(collection: Path, state: dict) -> bool:
    assets = state.get("assets")
    planning = state.get("planning")
    music = planning.get("music") if isinstance(planning, dict) else None
    if not isinstance(assets, dict) or not isinstance(music, dict):
        return False
    expected = music.get("expected_file_count")
    playlist_url = music.get("suno_playlist_url")
    prompts_path = collection / "20-documentation" / "suno-prompts.json"
    try:
        prompts_path = _confined_path(collection, prompts_path, "suno-prompts.json")
        prompts_data = json.loads(prompts_path.read_text(encoding="utf-8"))
    except (ValueError, OSError, json.JSONDecodeError):
        return False
    prompts = prompts_data.get("entries") if isinstance(prompts_data, dict) else prompts_data
    prompt_count = len(prompts) if isinstance(prompts, list) and all(isinstance(item, dict) for item in prompts) else 0
    minimum_expected = prompt_count * 2
    if (
        assets.get("music_downloaded") is not True
        or isinstance(expected, bool)
        or not isinstance(expected, int)
        or expected <= 0
        or minimum_expected <= 0
        or expected < minimum_expected
        or not isinstance(playlist_url, str)
        or not playlist_url.startswith("https://suno.com/playlist/")
    ):
        return False
    music_dir = collection / "02-Individual-music"
    try:
        music_dir = _confined_path(collection, music_dir, "02-Individual-music")
    except ValueError:
        return False
    if not music_dir.is_dir():
        return False
    count = sum(
        1
        for path in music_dir.iterdir()
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in AUDIO_SUFFIXES
    )
    return count >= expected


def _completed_tracking_matches(collection: Path, video_id: str) -> bool:
    tracking_path = collection / "20-documentation" / "upload_tracking.json"
    try:
        tracking_path = _confined_path(collection, tracking_path, "upload_tracking.json")
        tracking = _read_object(tracking_path)
    except ValueError:
        return False
    complete = tracking.get("complete_collection")
    return (
        tracking.get("schema_version") == 3
        and tracking.get("status") == "completed"
        and isinstance(complete, dict)
        and complete.get("status") == "completed"
        and secrets.compare_digest(str(complete.get("video_id", "")), video_id)
    )


def _local_publish_artifacts_complete(collection: Path, assets: dict) -> bool:
    video = assets.get("master_video")
    description = assets.get("description")
    if not (_artifact_file(collection, "01-master", video) and description is True):
        return False
    try:
        read_video_description_metadata(collection / "20-documentation" / "descriptions.json")
    except ValidationError:
        return False
    return True


def _publish_followup_complete(root: Path, collection: Path, video_id: str) -> bool:
    try:
        verify_post_publish_completion(root, collection)
    except (OSError, ValueError, StateSyncError, ValidationError):
        return False
    return True


def evaluate_collection(
    root: Path,
    collection: Path,
    config: RunnerConfig,
    *,
    executor: Literal["local", "cloud"] | None = None,
) -> Decision:
    root = root.resolve()
    collection = _inside(root, collection, "collection")
    state = _state(collection)
    phase = state["phase"]
    engine = _engine(state)
    assets = state.get("assets")
    upload = state.get("upload")
    if not isinstance(assets, dict) or not isinstance(upload, dict):
        raise ValueError("workflow-state.json::assets / upload は object でなければなりません")
    video_id = upload.get("video_id")
    stage = state.get("stage")

    handoff = state.handoff
    owner = "cloud" if phase == "planning" or (phase == "complete" and stage == "live") else "local"
    if handoff is not None and handoff.owner is not None:
        owner = handoff.owner
    if phase == "cloud_owned":
        if (
            handoff is None
            or handoff.point != "suno_download"
            or handoff.owner != "cloud"
            or handoff.manifest_key is None
            or handoff.root_sha256 is None
        ):
            raise ValueError("cloud_owned phase requires a complete cloud handoff reference")
    elif handoff is not None and handoff.owner == "cloud" and phase not in {"mastered", "publishing", "complete"}:
        raise ValueError("cloud handoff owner is inconsistent with workflow phase")
    if executor is not None and executor != owner:
        return _decision(
            collection=collection,
            phase=phase,
            engine=engine,
            action="no-op",
            reason=f"{owner}_ownership",
            config=config,
        )
    routing_phase = "prepared" if phase == "cloud_owned" else phase

    if isinstance(video_id, str) and video_id and (phase != "complete" or stage != "live"):
        if _completed_tracking_matches(collection, video_id):
            return _decision(
                collection=collection,
                phase=phase,
                engine=engine,
                action="wf-next",
                reason="upload_reconciliation_required",
                resume_action="wf-next",
                config=config,
            )
        return _decision(
            collection=collection,
            phase=phase,
            engine=engine,
            action="blocked",
            reason="upload_state_inconsistent",
            resume_action="wf-next",
            config=config,
        )
    if routing_phase == "planning":
        return _decision(
            collection=collection,
            phase=phase,
            engine=engine,
            action="wf-new",
            reason="planning_incomplete",
            resume_action="wf-new",
            config=config,
        )
    if routing_phase == "prepared":
        raw_master = assets.get("raw_master")
        if raw_master is not None:
            if not _artifact_file(collection, "01-master", raw_master):
                return _decision(
                    collection=collection,
                    phase=phase,
                    engine=engine,
                    action="blocked",
                    reason="raw_master_missing",
                    resume_action="wf-next",
                    config=config,
                )
            if not config.skip_audio_approval:
                return _decision(
                    collection=collection,
                    phase=phase,
                    engine=engine,
                    action="blocked",
                    reason="audio_approval_required",
                    resume_action="wf-next",
                    config=config,
                )
            return _decision(
                collection=collection,
                phase=phase,
                engine=engine,
                action="wf-next",
                reason="raw_master_ready",
                resume_action="wf-next",
                config=config,
            )
        if engine == "lyria":
            return _decision(
                collection=collection,
                phase=phase,
                engine=engine,
                action="lyria",
                reason="lyria_generation_required",
                resume_action="lyria",
                config=config,
            )
        if engine == "minimax":
            return _decision(
                collection=collection,
                phase=phase,
                engine=engine,
                action="minimax",
                reason="minimax_generation_required",
                resume_action="minimax",
                config=config,
            )
        if _suno_download_complete(collection, state):
            return _decision(
                collection=collection,
                phase=phase,
                engine=engine,
                action="masterup",
                reason="suno_download_complete",
                resume_action="masterup",
                config=config,
            )
        return _decision(
            collection=collection,
            phase=phase,
            engine=engine,
            action="suno-helper",
            reason="suno_artifacts_incomplete",
            resume_action="suno-helper",
            config=config,
        )

    if phase in {"mastered", "publishing"}:
        if not _artifact_file(collection, "01-master", assets.get("master_audio")):
            return _decision(
                collection=collection,
                phase=phase,
                engine=engine,
                action="blocked",
                reason="master_audio_missing",
                resume_action="wf-next",
                config=config,
            )
        if not _local_publish_artifacts_complete(collection, assets):
            return _decision(
                collection=collection,
                phase=phase,
                engine=engine,
                action="wf-next-local",
                reason="local_publish_artifacts_incomplete",
                resume_action="wf-next",
                config=config,
            )
        if not config.allow_external_publish:
            return _decision(
                collection=collection,
                phase=phase,
                engine=engine,
                action="blocked",
                reason="external_publish_disabled",
                resume_action="wf-next",
                config=config,
            )
        if not config.skip_upload_approval:
            return _decision(
                collection=collection,
                phase=phase,
                engine=engine,
                action="blocked",
                reason="upload_approval_required",
                resume_action="wf-next",
                config=config,
            )
        return _decision(
            collection=collection,
            phase=phase,
            engine=engine,
            action="wf-next",
            reason="publish_ready",
            resume_action="wf-next",
            config=config,
        )

    if not isinstance(video_id, str) or not video_id or state.get("stage") != "live":
        return _decision(
            collection=collection,
            phase=phase,
            engine=engine,
            action="blocked",
            reason="complete_state_missing_upload",
            resume_action="wf-next",
            config=config,
        )
    if config.post_publish_configured and not _publish_followup_complete(root, collection, video_id):
        if not config.allow_external_publish:
            return _decision(
                collection=collection,
                phase=phase,
                engine=engine,
                action="blocked",
                reason="external_publish_disabled",
                resume_action="post-publish",
                config=config,
            )
        return _decision(
            collection=collection,
            phase=phase,
            engine=engine,
            action="post-publish",
            reason="publish_followup_incomplete",
            resume_action="post-publish",
            config=config,
        )
    return _decision(
        collection=collection,
        phase=phase,
        engine=engine,
        action="complete",
        reason="all_steps_complete",
        config=config,
    )


def _state_dir(root: Path) -> Path:
    root = root.resolve()
    path = root / STATE_DIR_NAME
    if path.is_symlink():
        raise ValueError(f"{STATE_DIR_NAME} に symlink は使えません: {path}")
    path.mkdir(mode=0o700, exist_ok=True)
    return _confined_path(root, path, STATE_DIR_NAME)


@contextmanager
def _lease_mutex(root: Path):
    state_dir = _state_dir(root)
    mutex_path = state_dir / LEASE_MUTEX_NAME
    if mutex_path.is_symlink():
        raise ValueError(f"lease mutex に symlink は使えません: {mutex_path}")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(mutex_path, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield state_dir
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def acquire_lease(root: Path, *, now: float, ttl_seconds: int) -> str:
    if isinstance(ttl_seconds, bool) or ttl_seconds <= 0:
        raise ValueError("ttl_seconds は正の整数でなければなりません")
    # CLI 引数でオプションと誤認される `-` を含まない表現にする。
    token = secrets.token_hex(24)
    payload = {"token": token, "acquired_at": now, "expires_at": now + ttl_seconds}
    with _lease_mutex(root) as state_dir:
        lock_dir = state_dir / LEASE_DIR_NAME
        lease_path = lock_dir / LEASE_FILE_NAME
        if lock_dir.exists():
            if lock_dir.is_symlink() or not lock_dir.is_dir():
                raise ValueError(f"lease directory が不正です: {lock_dir}")
            try:
                lease = _read_object(lease_path)
                expires_at = lease.get("expires_at")
            except ValueError:
                # 全 lease writer は mutex 内で完成済み directory を rename するため、
                # JSON のない directory はクラッシュ残骸として安全に回収できる。
                shutil.rmtree(lock_dir)
            else:
                if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool) or expires_at > now:
                    raise LeaseBusyError("別の wf-new --auto が実行中です")
                shutil.rmtree(lock_dir)
        temporary = Path(tempfile.mkdtemp(prefix=".lease.", dir=state_dir))
        try:
            (temporary / LEASE_FILE_NAME).write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
            temporary.rename(lock_dir)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return token


def release_lease(root: Path, token: str) -> bool:
    with _lease_mutex(root) as state_dir:
        lock_dir = state_dir / LEASE_DIR_NAME
        lease_path = lock_dir / LEASE_FILE_NAME
        if lock_dir.is_symlink() or not lease_path.is_file() or lease_path.is_symlink():
            return False
        try:
            lease = _read_object(lease_path)
        except ValueError:
            return False
        if not secrets.compare_digest(str(lease.get("token", "")), token):
            return False
        shutil.rmtree(lock_dir)
        return True


def heartbeat_lease(root: Path, token: str, *, now: float, ttl_seconds: int) -> bool:
    if isinstance(ttl_seconds, bool) or ttl_seconds <= 0:
        raise ValueError("ttl_seconds は正の整数でなければなりません")
    with _lease_mutex(root) as state_dir:
        lease_path = state_dir / LEASE_DIR_NAME / LEASE_FILE_NAME
        if lease_path.is_symlink() or not lease_path.is_file():
            return False
        try:
            lease = _read_object(lease_path)
        except ValueError:
            return False
        expires_at = lease.get("expires_at")
        if (
            not secrets.compare_digest(str(lease.get("token", "")), token)
            or not isinstance(expires_at, (int, float))
            or isinstance(expires_at, bool)
            or expires_at <= now
        ):
            return False
        lease["expires_at"] = now + ttl_seconds
        descriptor, temporary_name = tempfile.mkstemp(prefix=".lease-json.", dir=lease_path.parent)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            temporary.write_text(json.dumps(lease, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(temporary, lease_path)
        finally:
            temporary.unlink(missing_ok=True)
        return True


def _owns_lease(root: Path, token: str) -> bool:
    with _lease_mutex(root) as state_dir:
        lease_path = state_dir / LEASE_DIR_NAME / LEASE_FILE_NAME
        if lease_path.is_symlink() or not lease_path.is_file():
            return False
        try:
            lease = _read_object(lease_path)
        except ValueError:
            return False
        expires_at = lease.get("expires_at")
        return (
            secrets.compare_digest(str(lease.get("token", "")), token)
            and isinstance(expires_at, (int, float))
            and not isinstance(expires_at, bool)
            and expires_at > time.time()
        )


def record_attempt(
    root: Path,
    *,
    token: str,
    collection: Path | None,
    action: str,
    status: Literal["success", "blocked", "failed"],
    reason: str,
    resume_action: str | None,
    now: str,
    segments: list[TimingSegment] | None = None,
) -> None:
    root = root.resolve()
    if collection is None:
        relative_collection = None
    else:
        collection = _inside(root, collection, "collection")
        _state(collection)
        relative_collection = collection.relative_to(root).as_posix()
    if action not in ACTIONS:
        raise ValueError(f"未知の action です: {action}")
    if resume_action is not None and resume_action not in ACTIONS:
        raise ValueError(f"未知の resume_action です: {resume_action}")
    if not reason:
        raise ValueError("reason は空でない文字列でなければなりません")
    try:
        datetime.fromisoformat(now)
    except ValueError as exc:
        raise ValueError(f"recorded_at は ISO 8601 でなければなりません: {now}") from exc
    with _lease_mutex(root) as state_dir:
        lease_path = state_dir / LEASE_DIR_NAME / LEASE_FILE_NAME
        try:
            lease = _read_object(lease_path)
        except ValueError as exc:
            raise LeaseBusyError(".automation-run history を更新する lease がありません") from exc
        expires_at = lease.get("expires_at")
        if (
            not secrets.compare_digest(str(lease.get("token", "")), token)
            or not isinstance(expires_at, (int, float))
            or isinstance(expires_at, bool)
            or expires_at <= time.time()
        ):
            raise LeaseBusyError(".automation-run history を更新する lease token の owner ではありません")
        history_path = state_dir / HISTORY_FILE_NAME
        if history_path.is_symlink():
            raise ValueError(f"history に symlink は使えません: {history_path}")
        history = read_history(root)
        history["schema_version"] = 2
        history["attempts"].append(
            {
                "run_id": hashlib.sha256(token.encode("utf-8")).hexdigest()[:16],
                "collection": relative_collection,
                "action": action,
                "status": status,
                "reason": reason,
                "resume_action": resume_action,
                "recorded_at": now,
                "timing": _attempt_timing(segments),
            }
        )
        descriptor, temporary_name = tempfile.mkstemp(prefix=".history.", dir=state_dir)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            temporary.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, history_path)
        finally:
            temporary.unlink(missing_ok=True)


def _load_runner_config(root: Path) -> RunnerConfig:
    previous = Path.cwd()
    previous_channel_dir = os.environ.get("CHANNEL_DIR")
    try:
        os.chdir(root)
        os.environ["CHANNEL_DIR"] = str(root.resolve())
        from youtube_automation.configuration import load_config, reset

        reset()
        config = load_config()
    finally:
        try:
            reset()
        except UnboundLocalError:
            pass
        if previous_channel_dir is None:
            os.environ.pop("CHANNEL_DIR", None)
        else:
            os.environ["CHANNEL_DIR"] = previous_channel_dir
        os.chdir(previous)
    return RunnerConfig(
        allow_external_publish=config.workflow.scheduled_automation.allow_external_publish,
        post_publish_configured=config.workflow.post_publish.configured,
        skip_audio_approval=config.workflow.wf_next.skip_audio_approval,
        skip_upload_approval=config.workflow.wf_next.skip_upload_approval,
    )


def resolve_action(
    root: Path,
    requested: str | None = None,
    *,
    config: RunnerConfig | None = None,
    executor: Literal["local", "cloud"] | None = None,
) -> Decision:
    """Return the next delegated action without mutating workflow state."""
    resolved_config = config or _load_runner_config(root)
    try:
        collection = select_collection(root, requested)
    except NoActiveCollectionError:
        if requested is not None:
            raise
        return {
            "collection": None,
            "phase": "absent",
            "engine": None,
            "action": "wf-new",
            "reason": "no_active_collection",
            "resume_action": "wf-new",
            "allow_external_publish": resolved_config.allow_external_publish,
        }
    return evaluate_collection(root, collection, resolved_config, executor=executor)


def record_bootstrap_attempt(
    root: Path,
    *,
    token: str,
    status: Literal["blocked", "failed"],
    reason: str,
    now: str,
    ai_started_at: str | None = None,
    human_intervals: list[list[str]] | None = None,
) -> None:
    """Record an unattended `/wf-new` stop before a collection exists."""
    if human_intervals and ai_started_at is None:
        raise ValueError("record-bootstrap: human_interval には ai_started_at が必要です")
    segments = _timing_segments(ai_started_at, human_intervals or [], now) if ai_started_at is not None else None
    record_attempt(
        root,
        token=token,
        collection=None,
        action="wf-new",
        status=status,
        reason=reason,
        resume_action="wf-new",
        now=now,
        segments=segments,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    acquire = sub.add_parser("acquire")
    acquire.add_argument("--channel-dir", type=Path, default=Path.cwd())
    acquire.add_argument("--ttl-seconds", type=int, default=21_600)
    heartbeat = sub.add_parser("heartbeat")
    heartbeat.add_argument("--channel-dir", type=Path, default=Path.cwd())
    heartbeat.add_argument("--token", required=True)
    heartbeat.add_argument("--ttl-seconds", type=int, default=21_600)
    release = sub.add_parser("release")
    release.add_argument("--channel-dir", type=Path, default=Path.cwd())
    release.add_argument("--token", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--channel-dir", type=Path, default=Path.cwd())
    plan.add_argument("--collection")
    plan.add_argument("--executor", choices=("local", "cloud"))
    record = sub.add_parser("record")
    record.add_argument("--channel-dir", type=Path, default=Path.cwd())
    record.add_argument("--token", required=True)
    record.add_argument("--collection", required=True)
    record.add_argument("--action", choices=sorted(ACTIONS), required=True)
    record.add_argument("--status", choices=("success", "blocked", "failed"), required=True)
    record.add_argument("--reason", required=True)
    record.add_argument("--resume-action", choices=sorted(ACTIONS))
    record.add_argument("--ai-started-at")
    record.add_argument("--human-interval", action="append", nargs=2, metavar=("START", "END"))
    bootstrap = sub.add_parser("record-bootstrap")
    bootstrap.add_argument("--channel-dir", type=Path, default=Path.cwd())
    bootstrap.add_argument("--token", required=True)
    bootstrap.add_argument("--status", choices=("blocked", "failed"), required=True)
    bootstrap.add_argument("--reason", required=True)
    bootstrap.add_argument("--ai-started-at")
    bootstrap.add_argument("--human-interval", action="append", nargs=2, metavar=("START", "END"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.channel_dir.resolve()
    try:
        if args.command == "acquire":
            token = acquire_lease(root, now=datetime.now(UTC).timestamp(), ttl_seconds=args.ttl_seconds)
            result = {"status": "acquired", "token": token}
        elif args.command == "heartbeat":
            refreshed = heartbeat_lease(
                root,
                args.token,
                now=datetime.now(UTC).timestamp(),
                ttl_seconds=args.ttl_seconds,
            )
            result = {"status": "refreshed" if refreshed else "not-owner"}
        elif args.command == "release":
            result = {"status": "released" if release_lease(root, args.token) else "not-owner"}
        elif args.command == "plan":
            result = resolve_action(root, args.collection, executor=args.executor)
        elif args.command == "record-bootstrap":
            recorded_at = datetime.now(UTC).isoformat()
            record_bootstrap_attempt(
                root,
                token=args.token,
                status=args.status,
                reason=args.reason,
                now=recorded_at,
                ai_started_at=args.ai_started_at,
                human_intervals=args.human_interval,
            )
            result = {"status": "recorded"}
        else:
            collection = select_collection(root, args.collection)
            recorded_at = datetime.now(UTC).isoformat()
            if args.human_interval and args.ai_started_at is None:
                raise ValueError("record: human_interval には ai_started_at が必要です")
            segments = (
                _timing_segments(args.ai_started_at, args.human_interval or [], recorded_at)
                if args.ai_started_at is not None
                else None
            )
            record_attempt(
                root,
                token=args.token,
                collection=collection,
                action=args.action,
                status=args.status,
                reason=args.reason,
                resume_action=args.resume_action,
                now=recorded_at,
                segments=segments,
            )
            result = {"status": "recorded"}
    except LeaseBusyError as exc:
        result = {"status": "busy", "reason": str(exc)}
        print(json.dumps(result, ensure_ascii=False))
        return 20
    except (OSError, ValueError) as exc:
        result = {"status": "error", "reason": str(exc)}
        print(json.dumps(result, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
