#!/usr/bin/env python3
"""Native scheduler plan and backend identity state for /automation-schedule (#2369)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from youtube_automation.utils.config import channel_dir, load_config

BACKENDS = (
    "codex-automation",
    "claude-code-cloud",
    "claude-cowork-local",
    "os-fallback",
)
PRODUCTS = ("codex", "claude")
DEPENDENCY_MODES = ("cloud", "local")


class BackendError(ValueError):
    """Backend selection or state transition is unsafe."""


def select_backend(*, product: str, dependency_mode: str, os_fallback: bool = False) -> str:
    """Select the native backend; OS fallback is never selected implicitly."""
    if os_fallback:
        return "os-fallback"
    if product == "codex":
        return "codex-automation"
    if product == "claude" and dependency_mode == "cloud":
        return "claude-code-cloud"
    if product == "claude" and dependency_mode == "local":
        return "claude-cowork-local"
    raise BackendError(f"unsupported product/dependency mode: {product}/{dependency_mode}")


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
    dependency_mode: str,
    os_fallback: bool = False,
    overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a product-neutral dry-run payload from effective workflow config."""
    config = load_config()
    scheduled = config.workflow.scheduled_automation
    overrides = overrides or {}
    run_time = str(overrides.get("run_time") or scheduled.run_time)
    raw_cadence = overrides.get("cadence") or list(scheduled.cadence)
    cadence = list(raw_cadence) if not isinstance(raw_cadence, str) else raw_cadence.split(",")
    target_workflow = str(overrides.get("target_workflow") or scheduled.target_workflow)
    max_retries = int(overrides.get("max_retries", scheduled.max_retries))
    retry_delay_seconds = int(overrides.get("retry_delay_seconds", scheduled.retry_delay_seconds))
    allow_external_publish = bool(overrides.get("allow_external_publish", scheduled.allow_external_publish))
    backend = select_backend(product=product, dependency_mode=dependency_mode, os_fallback=os_fallback)
    cwd = channel_dir().resolve()
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
        "target_workflow": target_workflow,
        "max_retries": max_retries,
        "retry_delay_seconds": retry_delay_seconds,
        "prevent_concurrent_runs": scheduled.prevent_concurrent_runs,
        "notification": overrides.get("notification", scheduled.notification),
        "allow_external_publish": allow_external_publish,
    }
    if backend == "codex-automation":
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
    plan.add_argument("--dependency-mode", choices=DEPENDENCY_MODES, required=True)
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
                    dependency_mode=args.dependency_mode,
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
