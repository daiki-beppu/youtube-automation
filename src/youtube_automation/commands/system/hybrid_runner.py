"""Canonical CLI for the platform-neutral hybrid sandwich runner."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from functools import partial
from pathlib import Path

from youtube_automation.application.hybrid_runner import HybridResourceEvent, SandwichRequest, run_sandwich
from youtube_automation.application.pipeline_notifications import PipelineNotificationBridge
from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.core.errors import ConfigError
from youtube_automation.infrastructure.hybrid_resources import SystemHybridResourceProbe
from youtube_automation.infrastructure.media_store.local import LocalMediaStore
from youtube_automation.infrastructure.media_store.r2 import R2MediaStore, R2MediaStoreConfig
from youtube_automation.infrastructure.notifications.discord import create_discord_notification_sink


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-dir", type=Path, default=Path.cwd())
    parser.add_argument("--channel-slug", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--collection-dir", required=True)
    parser.add_argument("--agent", choices=("claude", "codex"), default="claude")
    parser.add_argument("--stage", choices=("pipeline", "planning", "post-publish"), default="pipeline")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--commit-message", default="chore(hybrid): update workflow state")
    parser.add_argument("--input-handoff")
    parser.add_argument("--input-destination")
    parser.add_argument("--output-handoff")
    parser.add_argument("--output-root")
    parser.add_argument("--output-file", action="append", default=[])
    parser.add_argument("--media-store", choices=("r2", "local"), default="r2")
    parser.add_argument("--local-store-root", type=Path)
    parser.add_argument(
        "--generation-cost-usd",
        type=Decimal,
        default=Decimal("0"),
        help="このrunで新たに発生する生成従量費 (default: 0; 0円原則では正数を拒否)",
    )
    parser.add_argument(
        "--monthly-run-count",
        type=int,
        default=0,
        help="今月完了済みrun数の自己申告値 (default: 0)",
    )
    parser.add_argument(
        "--estimated-run-minutes",
        type=int,
        default=60,
        help="1 runの保守的なActions分数見積り (default: 60)",
    )
    return parser


def _report_resource_event(event: HybridResourceEvent) -> None:
    print(
        f"hybrid_resource_{event.kind.value}: channel={event.channel}, collection={event.collection}, {event.detail}",
        file=sys.stderr,
    )


def _handle_resource_event(event: HybridResourceEvent, *, notifications: PipelineNotificationBridge) -> None:
    _report_resource_event(event)
    notifications.hybrid_resources(event)


def run(args: argparse.Namespace) -> int:
    if args.media_store == "local":
        if args.local_store_root is None:
            raise ConfigError("--media-store local には --local-store-root が必要です")
        store = LocalMediaStore(args.local_store_root)
    else:
        if args.local_store_root is not None:
            raise ConfigError("--local-store-root は local MediaStore 専用です")
        store = R2MediaStore(R2MediaStoreConfig.from_environment())
    request = SandwichRequest(
        channel_dir=args.channel_dir.resolve(),
        collection_dir=args.collection_dir,
        channel=args.channel_slug,
        collection=args.collection,
        agent=args.agent,
        prompt=args.prompt,
        commit_message=args.commit_message,
        stage=args.stage,
        input_handoff=args.input_handoff,
        input_destination=args.input_destination,
        output_handoff=args.output_handoff,
        output_root=args.output_root,
        output_files=tuple(args.output_file),
    )
    resource_probe = SystemHybridResourceProbe(
        channel_dir=request.channel_dir,
        store=store,
        generation_cost_usd=args.generation_cost_usd,
        monthly_run_count=args.monthly_run_count,
        estimated_run_minutes=args.estimated_run_minutes,
    )
    notifications = PipelineNotificationBridge(create_discord_notification_sink())
    result = run_sandwich(
        request,
        store,
        resource_probe=resource_probe,
        on_resource_event=partial(_handle_resource_event, notifications=notifications),
        on_state_sync_event=partial(
            notifications.state_sync,
            channel=request.channel,
            collection=request.collection,
        ),
    )
    print(f"hybrid runner {result.status}: {result.collection or 'new'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(build_parser, run, argv, failure_message="sandwich runner error")


if __name__ == "__main__":
    raise SystemExit(main())
