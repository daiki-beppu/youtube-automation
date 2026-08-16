"""Report the monthly Codex escape canary result through the notification owner."""

from __future__ import annotations

import argparse
import sys

from youtube_automation.application.pipeline_notifications import PipelineNotificationBridge
from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.domains.notifications import NotificationEventKind
from youtube_automation.infrastructure.notifications.discord import create_discord_notification_sink

_COLLECTION = "monthly-codex-canary"
_STAGE = "codex-action"
_RESULTS = ("success", "failure", "cancelled", "skipped")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", choices=_RESULTS, required=True)
    parser.add_argument("--channel", required=True)
    return parser


def run(args: argparse.Namespace) -> int:
    kind = NotificationEventKind.CANARY_COMPLETED if args.result == "success" else NotificationEventKind.CANARY_FAILED
    delivered = PipelineNotificationBridge(create_discord_notification_sink()).emit(
        kind,
        channel=args.channel,
        collection=_COLLECTION,
        stage=_STAGE,
    )
    if not delivered:
        print("Codex canary notification was not delivered", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="Codex canary notification failed")


if __name__ == "__main__":
    raise SystemExit(main())
