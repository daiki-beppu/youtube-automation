"""Generate deterministic human-tasks.md and send its Discord summary."""

from __future__ import annotations

import argparse

from youtube_automation.application.human_tasks import generate_human_tasks
from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.configuration import channel_dir, load_config
from youtube_automation.infrastructure.notifications.discord import create_discord_notification_sink


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description=__doc__)


def run(args: argparse.Namespace) -> int:
    del args
    config = load_config()
    result = generate_human_tasks(
        channel_dir(),
        channel=config.meta.channel_short,
        distrokid_enabled=config.distrokid.enabled,
        notifier=create_discord_notification_sink(),
    )
    print(f"{result.path} (pending={len(result.report.tasks)})")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="human tasks generation failed")


if __name__ == "__main__":
    raise SystemExit(main())
