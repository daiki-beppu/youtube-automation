#!/usr/bin/env python3
"""Resolve canonical `/wf-auto` actions and maintain its lease/history state."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
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

STATE_DIR_NAME = ".automation-run"
LEASE_DIR_NAME = "lease"
LEASE_FILE_NAME = "lease.json"
LEASE_MUTEX_NAME = "lease.mutex"
HISTORY_FILE_NAME = "history.json"
AUDIO_SUFFIXES = {".mp3", ".m4a", ".wav", ".flac", ".aac"}
POST_PUBLISH_STEPS = ("community-post", "pinned-comment", "metadata-audit")
PHASES = {"planning", "prepared", "mastered", "publishing", "complete"}
ENGINES = {"suno", "lyria"}
ACTIONS = {
    "wf-new",
    "lyria",
    "suno-helper",
    "masterup",
    "wf-next-local",
    "wf-next",
    "post-publish",
    "blocked",
    "complete",
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


def _read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON を読めません: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root は object でなければなりません: {path}")
    return value


def _inside(root: Path, path: Path, field: str) -> Path:
    root = root.resolve()
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} は channel-dir 配下でなければなりません") from exc
    return path


def _state(collection: Path) -> dict:
    state_path = collection / "workflow-state.json"
    if state_path.is_symlink() or not state_path.is_file():
        raise ValueError(f"workflow-state.json は通常ファイルでなければなりません: {state_path}")
    state = _read_object(state_path)
    phase = state.get("phase")
    if phase not in PHASES:
        raise ValueError(f"未対応 phase です: {phase!r}")
    return state


def _engine(state: dict) -> str:
    top_level = state.get("music_engine")
    planning = state.get("planning")
    planning_music = planning.get("music") if isinstance(planning, dict) else None
    nested = planning_music.get("engine") if isinstance(planning_music, dict) else None
    if top_level in ENGINES and nested in ENGINES and top_level != nested:
        raise ValueError(f"music engine が不一致です: top-level={top_level}, planning.music={nested}")
    engine = nested or top_level
    if engine not in ENGINES:
        raise ValueError(f"未対応 music engine です: {engine!r}")
    return engine


def _collection_sort_key(collection: Path) -> tuple[str, str]:
    state = _state(collection)
    created_at = state.get("created_at")
    return (created_at if isinstance(created_at, str) else "9999", collection.name)


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
            if _state(collection).get("phase") != "complete":
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
    return (
        _artifact_file(collection, "01-master", video)
        and description is True
        and (collection / "20-documentation" / "descriptions.md").is_file()
    )


def _post_publish_complete(root: Path, video_id: str) -> bool:
    history_path = root / "post_publish_history.json"
    if not history_path.is_file():
        return False
    history = _read_object(history_path)
    if history.get("schema_version") != 1:
        raise ValueError(f"未対応 post-publish history schema です: {history_path}")
    videos = history.get("videos")
    video = videos.get(video_id) if isinstance(videos, dict) else None
    completed = video.get("completed") if isinstance(video, dict) else None
    return isinstance(completed, dict) and all(
        isinstance(completed.get(step), str) and completed[step] for step in POST_PUBLISH_STEPS
    )


def evaluate_collection(root: Path, collection: Path, config: RunnerConfig) -> Decision:
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
    if phase == "planning":
        return _decision(
            collection=collection,
            phase=phase,
            engine=engine,
            action="wf-new",
            reason="planning_incomplete",
            resume_action="wf-new",
            config=config,
        )
    if phase == "prepared":
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
    if config.post_publish_configured and not _post_publish_complete(root, video_id):
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
            reason="post_publish_incomplete",
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
    token = secrets.token_urlsafe(24)
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
                    raise LeaseBusyError("別の wf-auto が実行中です")
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
        history = _read_object(history_path) if history_path.exists() else {"schema_version": 1, "attempts": []}
        if history.get("schema_version") != 1 or not isinstance(history.get("attempts"), list):
            raise ValueError(f"未対応 .automation-run history です: {history_path}")
        history["attempts"].append(
            {
                "run_id": hashlib.sha256(token.encode("utf-8")).hexdigest()[:16],
                "collection": relative_collection,
                "action": action,
                "status": status,
                "reason": reason,
                "resume_action": resume_action,
                "recorded_at": now,
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
        from youtube_automation.utils.config import load_config, reset

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
    return evaluate_collection(root, collection, resolved_config)


def record_bootstrap_attempt(
    root: Path,
    *,
    token: str,
    status: Literal["blocked", "failed"],
    reason: str,
    now: str,
) -> None:
    """Record an unattended `/wf-new` stop before a collection exists."""
    record_attempt(
        root,
        token=token,
        collection=None,
        action="wf-new",
        status=status,
        reason=reason,
        resume_action="wf-new",
        now=now,
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
    record = sub.add_parser("record")
    record.add_argument("--channel-dir", type=Path, default=Path.cwd())
    record.add_argument("--token", required=True)
    record.add_argument("--collection", required=True)
    record.add_argument("--action", choices=sorted(ACTIONS), required=True)
    record.add_argument("--status", choices=("success", "blocked", "failed"), required=True)
    record.add_argument("--reason", required=True)
    record.add_argument("--resume-action", choices=sorted(ACTIONS))
    bootstrap = sub.add_parser("record-bootstrap")
    bootstrap.add_argument("--channel-dir", type=Path, default=Path.cwd())
    bootstrap.add_argument("--token", required=True)
    bootstrap.add_argument("--status", choices=("blocked", "failed"), required=True)
    bootstrap.add_argument("--reason", required=True)
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
            result = resolve_action(root, args.collection)
        elif args.command == "record-bootstrap":
            record_bootstrap_attempt(
                root,
                token=args.token,
                status=args.status,
                reason=args.reason,
                now=datetime.now(UTC).isoformat(),
            )
            result = {"status": "recorded"}
        else:
            collection = select_collection(root, args.collection)
            record_attempt(
                root,
                token=args.token,
                collection=collection,
                action=args.action,
                status=args.status,
                reason=args.reason,
                resume_action=args.resume_action,
                now=datetime.now(UTC).isoformat(),
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
