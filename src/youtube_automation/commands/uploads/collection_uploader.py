"""Command adapter for collection uploads."""

import argparse
import logging

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.core.errors import AutomationError
from youtube_automation.domains.uploads.collection import CollectionUploader
from youtube_automation.infrastructure.google.youtube import create_authenticated_youtube_clients


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Complete Collection を YouTube へアップロードする")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--daemon", "-d", action="store_true")
    parser.add_argument("--collection", "-c")
    parser.add_argument("--config")
    return parser


def run(args: argparse.Namespace) -> None:
    uploader = CollectionUploader(
        config_path=args.config,
        youtube_clients=create_authenticated_youtube_clients(),
    )
    if args.daemon:
        uploader.run_automated_schedule()
        return
    target = uploader.find_collection(args.collection)
    if target:
        if not args.status:
            uploader.ensure_upload_preflight(target)
        action = (
            uploader.show_status if args.status else uploader.show_plan if args.plan else uploader.execute_next_step
        )
        action(target)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    return run_cli(
        build_parser,
        run,
        argv,
        failure_message="エラー",
        interrupt_message="処理が中断されました",
        interrupt_exit_code=None,
        handled_errors=(AutomationError, OSError, ValueError),
    )
