"""Lightweight, argparse-compatible command error boundary."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from youtube_automation.core.errors import AutomationError
from youtube_automation.infrastructure.auth.redaction import redact_sensitive_data

ParserBuilder = Callable[[], argparse.ArgumentParser]
CommandRunner = Callable[[argparse.Namespace], int | None]


def run_cli(
    build_parser: ParserBuilder,
    run: CommandRunner,
    argv: list[str] | None = None,
    *,
    failure_message: str = "エラー",
    failure_exit_code: int = 1,
    interrupt_message: str = "中断されました",
    interrupt_exit_code: int | None = 130,
    handled_errors: tuple[type[Exception], ...] = (AutomationError,),
) -> int:
    """Parse arguments, run a command, and normalize its expected boundary errors."""
    try:
        args = build_parser().parse_args(argv)
        exit_code = run(args)
    except KeyboardInterrupt:
        print(f"\n🛑 {interrupt_message}")
        return 0 if interrupt_exit_code is None else interrupt_exit_code
    except handled_errors as exc:
        print(f"❌ {failure_message}: {redact_sensitive_data(str(exc))}", file=sys.stderr)
        return failure_exit_code
    return 0 if exit_code is None else exit_code
