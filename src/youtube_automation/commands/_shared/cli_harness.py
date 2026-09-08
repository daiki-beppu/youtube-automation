"""Lightweight, argparse-compatible command error boundary."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable

from youtube_automation.core.errors import AutomationError, ConfigError, ValidationError
from youtube_automation.core.redaction import redact_sensitive_data

ParserBuilder = Callable[[], argparse.ArgumentParser]
CommandRunner = Callable[[argparse.Namespace], int | None]

# Upload commands report expected domain, filesystem, and input failures at the CLI boundary.
UPLOAD_COMMAND_ERRORS = (AutomationError, OSError, ValueError)


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


def run_logged_command(action: Callable[[], int], logger: logging.Logger) -> int:
    """Report configuration, domain, filesystem, and input failures at the CLI boundary."""
    try:
        return action()
    except ConfigError as error:
        logger.error(str(error))
        return 2
    except (AutomationError, OSError, ValueError) as error:
        logger.exception(f"エラー: {error}")
        return 1


def print_json_or_text_report(
    report: dict[str, object], *, text: bool, render_text: Callable[[dict[str, object]], None]
) -> None:
    """Print a report using its text renderer or the standard readable JSON format."""
    if text:
        render_text(report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))


def run_report_command(
    load_report: Callable[[], dict[str, object]],
    *,
    text: bool,
    render_text: Callable[[dict[str, object]], None],
    logger: logging.Logger,
    failure_message: str,
) -> int:
    """Report expected domain, filesystem, and input failures with their exit codes."""
    try:
        report = load_report()
        print_json_or_text_report(report, text=text, render_text=render_text)
        return 0
    except AutomationError as error:
        logger.error(str(error))
        return 2
    except (OSError, ValueError) as error:
        logger.exception(failure_message, error)
        return 1


def run_validated_command(action: Callable[[], int]) -> int:
    """Run commands whose config/validation failures use a plain stderr diagnostic."""
    try:
        return action()
    except (ValidationError, ConfigError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


def print_candidate_review_result(
    status: str,
    artifact_digest: str | None,
    candidate_id: str | None,
    candidates: tuple[str, ...],
    *,
    candidate_format: str,
) -> int:
    """Print a candidate review result and its terminal-selection continuation hint."""
    print(
        json.dumps(
            {
                "status": status,
                "artifact_digest": artifact_digest,
                "candidate_id": candidate_id,
                "candidates": list(candidates),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if status == "terminal_required":
        print(f"候補を確認後、--candidate-id <{candidate_format}>を指定してください", file=sys.stderr)
        return 2
    return 0
