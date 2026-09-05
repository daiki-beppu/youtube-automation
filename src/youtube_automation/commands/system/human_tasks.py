"""Generate deterministic human-tasks.md and send its Discord summary."""

from __future__ import annotations

import argparse
from pathlib import Path

from youtube_automation.application.human_tasks import generate_human_tasks
from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.configuration.loader import load_config_from_path
from youtube_automation.infrastructure.notifications.discord import create_discord_notification_sink


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-dir", type=Path, default=Path.cwd())
    return parser


def run(args: argparse.Namespace) -> int:
    channel_root = args.channel_dir.resolve()
    config = load_config_from_path(channel_root)
    result = generate_human_tasks(
        channel_root,
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
