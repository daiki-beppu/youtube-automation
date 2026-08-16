#!/usr/bin/env python3
"""Scheduler plan and backend identity state for /wf-new --schedule."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from youtube_automation.configuration import channel_dir, load_config

BACKENDS = (
    "codex-automation",
    "claude-code-cloud",
    "claude-cowork-local",
    "os-fallback",
    "github-actions",
)
PRODUCTS = ("codex", "claude")
EXECUTION_STAGES = ("planning", "prompt", "suno", "media", "publish")
WRITE_TOKEN_REFRESH_COMMAND = "uv run yt-oauth --refresh-only"
WRITE_TOKEN_REAUTH_COMMAND = "uv run yt-oauth"


class BackendError(ValueError):
    """Backend selection or state transition is unsafe."""


def classify_dependency_mode(*, stage: str, overlays_enabled: bool) -> tuple[str, str]:
    """Classify a workflow stage by required capability, plus the heavy-media exception."""
    if stage not in EXECUTION_STAGES:
        raise BackendError(f"unsupported execution stage: {stage}")
    if stage in {"planning", "prompt"}:
        return "cloud", "ai_stage_cloud"
    if stage == "suno":
        return "local", "human_browser_required"
    if overlays_enabled:
        return "local", "heavy_overlay_temporary_exception"
    return "cloud", "lightweight_media_cloud"


def select_backend(*, product: str, dependency_mode: str, os_fallback: bool = False) -> str:
    """Select the capability-compatible backend; OS fallback is never implicit."""
    if product not in PRODUCTS or dependency_mode not in {"cloud", "local"}:
        raise BackendError(f"unsupported product/dependency mode: {product}/{dependency_mode}")
    if os_fallback:
        return "os-fallback"
    if dependency_mode == "cloud":
        return "github-actions"
    if product == "codex":
        return "codex-automation"
    if product == "claude":
        return "claude-cowork-local"
    raise BackendError(f"unsupported product/dependency mode: {product}/{dependency_mode}")


def _fixed_utc_offset(timezone_name: str) -> timedelta:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise BackendError(f"unknown timezone: {timezone_name}") from exc
    start_year = datetime.now(UTC).year
    offsets = {
        datetime(year, month, day, 12, tzinfo=timezone).utcoffset()
        for year in (start_year, start_year + 1)
        for month in range(1, 13)
        for day in (1, 15)
    }
    if None in offsets or len(offsets) != 1:
        raise BackendError(f"GitHub Actions cron cannot preserve a variable UTC offset timezone: {timezone_name}")
    return offsets.pop()


def github_actions_cron(*, run_time: str, cadence: list[str], timezone_name: str) -> str:
    """Convert a fixed-offset local weekly schedule to GitHub's UTC cron."""
    day_indexes = {day: index for index, day in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}
    try:
        hour_text, minute_text = run_time.split(":", maxsplit=1)
        hour, minute = int(hour_text), int(minute_text)
        local_days = [day_indexes[day] for day in cadence]
    except (ValueError, KeyError) as exc:
        raise BackendError("run_time or cadence is invalid for GitHub Actions cron") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59 or not local_days:
        raise BackendError("run_time or cadence is invalid for GitHub Actions cron")
    offset = _fixed_utc_offset(timezone_name)
    offset_minutes = int(offset.total_seconds() // 60)
    day_delta, utc_minutes = divmod(hour * 60 + minute - offset_minutes, 24 * 60)
    utc_hour, utc_minute = divmod(utc_minutes, 60)
    cron_days = sorted({(day + day_delta + 1) % 7 for day in local_days})
    day_field = "*" if len(cron_days) == 7 else ",".join(str(day) for day in cron_days)
    return f"{utc_minute} {utc_hour} * * {day_field}"


def _rrule(run_time: str, cadence: list[str]) -> str:
    day_map = {
        "mon": "MO",
        "tue": "TU",
        "wed": "WE",
        "thu": "TH",
        "fri": "FR",
        "sat": "SA",
        "sun": "SU",
    }
    hour, minute = (int(part) for part in run_time.split(":", maxsplit=1))
    days = ",".join(day_map[day] for day in cadence)
    return f"RRULE:FREQ=WEEKLY;BYDAY={days};BYHOUR={hour};BYMINUTE={minute}"


def build_plan(
    *,
    product: str,
    stage: str,
    os_fallback: bool = False,
    overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a product-neutral dry-run payload from effective workflow config."""
    config = load_config()
    scheduled = config.workflow.scheduled_automation
    dependency_mode, boundary_reason = classify_dependency_mode(
        stage=stage,
        overlays_enabled=config.youtube.overlays.enabled,
    )
    overrides = overrides or {}
    run_time = str(overrides.get("run_time") or scheduled.run_time)
    raw_cadence = overrides.get("cadence") or list(scheduled.cadence)
    cadence = list(raw_cadence) if not isinstance(raw_cadence, str) else raw_cadence.split(",")
    target_workflow = str(overrides.get("target_workflow") or scheduled.target_workflow)
    if target_workflow in {"automation-run", "wf-auto"}:
        raise BackendError(
            f"--target-workflow {target_workflow} は廃止されました。"
            "--target-workflow 'wf-new --auto' へ更新してください"
        )
    max_retries = int(overrides.get("max_retries", scheduled.max_retries))
    retry_delay_seconds = int(overrides.get("retry_delay_seconds", scheduled.retry_delay_seconds))
    allow_external_publish = bool(overrides.get("allow_external_publish", scheduled.allow_external_publish))
    backend = select_backend(product=product, dependency_mode=dependency_mode, os_fallback=os_fallback)
    cwd = channel_dir().resolve()
    if dependency_mode == "local":
        prompt = (
            "定期実行の開始時に write OAuth token の保守として "
            f"`{WRITE_TOKEN_REFRESH_COMMAND}` を1回だけ実行する。"
            "この更新は YouTube Data API を呼び出さない。更新に失敗した場合は workflow を開始せず、"
            "認証エラーをそのまま再試行せずに停止し、対話可能なターミナルで "
            f"`{WRITE_TOKEN_REAUTH_COMMAND}` を実行するよう報告する。"
            f"\n\n更新成功後に /{target_workflow} を実行する。"
        )
    else:
        prompt = f"/{target_workflow}"
    if not allow_external_publish:
        prompt += "\n\n制約: YouTube への書き込みは実行せず、外部反映を伴うステップの直前で停止して報告する。"
    if max_retries:
        prompt += (
            f"\n\n一時的な失敗では {retry_delay_seconds} 秒待って最大 {max_retries} 回再試行する。"
            "認証・権限・手動介入が必要な失敗は再試行せず停止して報告する。"
        )
    plan: dict[str, object] = {
        "dry_run": True,
        "backend": backend,
        "job_key": f"youtube-automation:{cwd.name}",
        "title": f"youtube-automation / {cwd.name}",
        "prompt": prompt,
        "cwd": str(cwd),
        "timezone": str(overrides.get("timezone") or scheduled.timezone),
        "recurrence": _rrule(run_time, cadence),
        "dependency_mode": dependency_mode,
        "boundary_reason": boundary_reason,
        "target_workflow": target_workflow,
        "max_retries": max_retries,
        "retry_delay_seconds": retry_delay_seconds,
        "prevent_concurrent_runs": scheduled.prevent_concurrent_runs,
        "notification": overrides.get("notification", scheduled.notification),
        "allow_external_publish": allow_external_publish,
    }
    plan["execution_stage"] = stage
    if backend == "github-actions":
        if not scheduled.prevent_concurrent_runs:
            raise BackendError("github-actions backend requires prevent_concurrent_runs: true")
        plan["cron"] = github_actions_cron(
            run_time=run_time,
            cadence=cadence,
            timezone_name=str(plan["timezone"]),
        )
        plan["management"] = "GitHub Actions workflow schedule trigger"
    elif backend == "codex-automation":
        plan["management"] = "ChatGPT desktop/web Scheduled; local dependencies require desktop local project"
    elif backend == "claude-code-cloud":
        plan["management"] = "Claude Code /schedule Cloud Job"
    elif backend == "claude-cowork-local":
        plan["management"] = "Claude Cowork Scheduled task with the local folder selected"
    else:
        plan["management"] = "scheduler_job.sh explicit launchd/cron fallback"
        plan["warning"] = "OS fallback requires explicit user selection and --confirm-os-fallback"
    return plan


def default_state_path(channel_root: Path) -> Path:
    """Keep machine-specific backend identity in git metadata, never tracked files."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-path", "youtube-automation-schedule.json"],
        cwd=channel_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        path = Path(result.stdout.strip())
        return path if path.is_absolute() else channel_root / path
    digest = hashlib.sha256(str(channel_root.resolve()).encode()).hexdigest()[:16]
    return Path.home() / ".local" / "state" / "youtube-automation" / f"schedule-{digest}.json"


def read_state(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BackendError(f"backend state must be an object: {path}")
    return payload


def ensure_backend_available(path: Path, *, backend: str) -> dict[str, object]:
    """Reject a second active backend before any external scheduler mutation."""
    current = read_state(path)
    if current and current.get("status") == "active" and current.get("backend") != backend:
        raise BackendError(f"active backend {current.get('backend')} exists; disable it before using {backend}")
    return current or {"status": "available", "backend": backend}


def record_state(path: Path, *, backend: str, external_id: str, replace_backend: bool = False) -> dict[str, object]:
    if not replace_backend:
        ensure_backend_available(path, backend=backend)
    payload: dict[str, object] = {
        "backend": backend,
        "external_id": external_id,
        "status": "active",
        "updated_at": datetime.now(UTC).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def disable_state(path: Path, *, backend: str) -> dict[str, object]:
    current = read_state(path)
    if current is None:
        raise BackendError("backend state is not recorded")
    if current.get("backend") != backend:
        raise BackendError(f"recorded backend is {current.get('backend')}, not {backend}")
    current["status"] = "disabled"
    current["updated_at"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return current


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-dir", type=Path, default=Path.cwd())
    parser.add_argument("--state-path", type=Path, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--product", choices=PRODUCTS, required=True)
    plan.add_argument("--stage", choices=EXECUTION_STAGES, required=True)
    plan.add_argument("--os-fallback", action="store_true")
    plan.add_argument("--timezone")
    plan.add_argument("--run-time")
    plan.add_argument("--cadence")
    plan.add_argument("--target-workflow")
    plan.add_argument("--max-retries", type=int)
    plan.add_argument("--retry-delay-seconds", type=int)
    plan.add_argument("--notification")
    plan.add_argument("--allow-external-publish", action="store_true")

    sub.add_parser("show")
    guard = sub.add_parser("guard")
    guard.add_argument("--backend", choices=BACKENDS, required=True)
    record = sub.add_parser("record")
    record.add_argument("--backend", choices=BACKENDS, required=True)
    record.add_argument("--external-id", required=True)
    record.add_argument("--replace-backend", action="store_true")
    disable = sub.add_parser("disable")
    disable.add_argument("--backend", choices=BACKENDS, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.channel_dir.resolve()
    state_path = args.state_path or default_state_path(root)
    try:
        if args.command == "plan":
            previous_cwd = Path.cwd()
            try:
                os.chdir(root)
                payload = build_plan(
                    product=args.product,
                    stage=args.stage,
                    os_fallback=args.os_fallback,
                    overrides={
                        key: value
                        for key in (
                            "timezone",
                            "run_time",
                            "cadence",
                            "target_workflow",
                            "max_retries",
                            "retry_delay_seconds",
                            "notification",
                            "allow_external_publish",
                        )
                        if (value := getattr(args, key)) is not None
                    },
                )
            finally:
                os.chdir(previous_cwd)
        elif args.command == "show":
            payload = read_state(state_path) or {"status": "unconfigured"}
        elif args.command == "guard":
            payload = ensure_backend_available(state_path, backend=args.backend)
        elif args.command == "record":
            payload = record_state(
                state_path,
                backend=args.backend,
                external_id=args.external_id,
                replace_backend=args.replace_backend,
            )
        else:
            payload = disable_state(state_path, backend=args.backend)
    except (BackendError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
