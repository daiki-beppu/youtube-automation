#!/usr/bin/env python3
"""Return the resumable state of the setup tool step as JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TypedDict

from youtube_automation.commands.system import doctor
from youtube_automation.core.errors import ConfigError

EXIT_SKIP = 0
EXIT_RUN = 10
EXIT_ERROR = 2
_STEPS = ("tool",)
_UNRESOLVED_STATUSES = frozenset({"fail", "warn", "unknown"})


class CheckPayload(TypedDict):
    id: str
    status: str


class StateResult(TypedDict):
    step: str
    decision: str
    reason: str
    checks: list[CheckPayload]


def _payload(checks: list[doctor.CheckResult]) -> list[CheckPayload]:
    return [{"id": check.id, "status": check.status} for check in checks]


def evaluate(checks: list[doctor.CheckResult], step: str) -> tuple[int, StateResult]:
    if step not in _STEPS:
        raise ValueError(f"unknown setup step: {step}")

    unresolved = [check for check in checks if check.status in _UNRESOLVED_STATUSES]
    if not unresolved:
        return EXIT_SKIP, {
            "step": step,
            "decision": "skip",
            "reason": "setup_ready",
            "checks": [],
        }
    if len(unresolved) == 1 and unresolved[0].id == "analytics_report" and unresolved[0].status == "fail":
        return EXIT_SKIP, {
            "step": step,
            "decision": "skip",
            "reason": "setup_ready_analytics_report_stale",
            "checks": _payload(unresolved),
        }
    return EXIT_RUN, {
        "step": step,
        "decision": "run",
        "reason": "setup_checks_unresolved",
        "checks": _payload(unresolved),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-dir", type=Path, default=Path.cwd())
    parser.add_argument("--step", choices=_STEPS, required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        code, result = evaluate(doctor.run_all_checks(args.channel_dir.resolve()), args.step)
    except (ConfigError, OSError, ValueError) as exc:
        code = EXIT_ERROR
        result = {"step": args.step, "decision": "error", "reason": str(exc), "checks": []}
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
