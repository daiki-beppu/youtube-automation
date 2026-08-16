#!/usr/bin/env python3
"""Manage the owned schedule block in the distributed channel workflow."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from contextlib import suppress
from pathlib import Path

WORKFLOW_PATH = Path(".github/workflows/youtube-automation.yml")
SCHEDULE_BEGIN = "  # yt-automation-schedule:begin"
SCHEDULE_END = "  # yt-automation-schedule:end"
_ACTIVE_BLOCK = re.compile(r'\n  schedule:\n    - cron: "([^"]+)"\n\Z')


class ScheduleWorkflowError(ValueError):
    """The workflow cannot be safely managed by this adapter."""


def _workflow_target(channel_dir: Path) -> Path:
    root = channel_dir.resolve()
    target = root / WORKFLOW_PATH
    current = root
    for part in WORKFLOW_PATH.parts:
        current = current / part
        if current.is_symlink():
            raise ScheduleWorkflowError(f"workflow path contains a symlink: {current}")
    return target


def _read_workflow(channel_dir: Path) -> tuple[Path, str] | None:
    target = _workflow_target(channel_dir)
    if not target.exists():
        return None
    if not target.is_file():
        raise ScheduleWorkflowError(f"workflow is not a regular file: {target}")
    return target, target.read_text(encoding="utf-8")


def _managed_parts(text: str) -> tuple[str, str, str]:
    if text.count(SCHEDULE_BEGIN) != 1 or text.count(SCHEDULE_END) != 1:
        raise ScheduleWorkflowError("workflow schedule management markers are missing or duplicated")
    prefix, remainder = text.split(SCHEDULE_BEGIN, maxsplit=1)
    managed, suffix = remainder.split(SCHEDULE_END, maxsplit=1)
    return prefix, managed, suffix


def _validated_cron(cron: str) -> str:
    fields = cron.split()
    if len(fields) != 5 or fields[2:4] != ["*", "*"]:
        raise ScheduleWorkflowError(f"unsupported GitHub Actions cron: {cron!r}")
    minute_text, hour_text, _, _, days_text = fields
    if not minute_text.isdigit() or not hour_text.isdigit():
        raise ScheduleWorkflowError(f"unsupported GitHub Actions cron: {cron!r}")
    minute, hour = int(minute_text), int(hour_text)
    if not 0 <= minute <= 59 or not 0 <= hour <= 23:
        raise ScheduleWorkflowError(f"unsupported GitHub Actions cron: {cron!r}")
    if days_text != "*":
        days = days_text.split(",")
        if not days or any(not day.isdigit() or not 0 <= int(day) <= 6 for day in days):
            raise ScheduleWorkflowError(f"unsupported GitHub Actions cron: {cron!r}")
        if [int(day) for day in days] != sorted({int(day) for day in days}):
            raise ScheduleWorkflowError(f"GitHub Actions cron weekdays must be unique and sorted: {cron!r}")
    return f"{minute} {hour} * * {days_text}"


def _atomic_write(target: Path, text: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, target.stat().st_mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        directory_descriptor = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        with suppress(OSError):
            os.close(descriptor)
        with suppress(OSError):
            temporary.unlink()
        raise


def _result(*, status: str, cron: str | None = None) -> dict[str, str]:
    result = {
        "backend": "github-actions",
        "status": status,
        "workflow": str(WORKFLOW_PATH),
    }
    if cron is not None:
        result["cron"] = cron
    return result


def configure_schedule(channel_dir: Path, *, cron: str) -> dict[str, str]:
    validated = _validated_cron(cron)
    loaded = _read_workflow(channel_dir)
    if loaded is None:
        raise ScheduleWorkflowError(
            "distributed workflow is missing; run `uv run yt-skills sync --asset channel-workflow` first"
        )
    target, text = loaded
    prefix, _, suffix = _managed_parts(text)
    managed = f'\n  schedule:\n    - cron: "{validated}"\n'
    updated = prefix + SCHEDULE_BEGIN + managed + SCHEDULE_END + suffix
    if updated != text:
        _atomic_write(target, updated)
    return _result(status="active", cron=validated)


def schedule_status(channel_dir: Path) -> dict[str, str]:
    loaded = _read_workflow(channel_dir)
    if loaded is None:
        return _result(status="unconfigured")
    _, text = loaded
    _, managed, _ = _managed_parts(text)
    if managed == "\n":
        return _result(status="disabled")
    match = _ACTIVE_BLOCK.fullmatch(managed)
    if match is None:
        raise ScheduleWorkflowError("managed workflow schedule block has an unsupported shape")
    return _result(status="active", cron=_validated_cron(match.group(1)))


def disable_schedule(channel_dir: Path) -> dict[str, str]:
    loaded = _read_workflow(channel_dir)
    if loaded is None:
        raise ScheduleWorkflowError("distributed workflow is missing; nothing can be disabled")
    target, text = loaded
    prefix, _, suffix = _managed_parts(text)
    updated = prefix + SCHEDULE_BEGIN + "\n" + SCHEDULE_END + suffix
    if updated != text:
        _atomic_write(target, updated)
    return _result(status="disabled")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-dir", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    configure = sub.add_parser("configure")
    configure.add_argument("--cron", required=True)
    sub.add_parser("status")
    sub.add_parser("disable")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "configure":
            result = configure_schedule(args.channel_dir, cron=args.cron)
        elif args.command == "status":
            result = schedule_status(args.channel_dir)
        else:
            result = disable_schedule(args.channel_dir)
    except (OSError, UnicodeError, ScheduleWorkflowError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
