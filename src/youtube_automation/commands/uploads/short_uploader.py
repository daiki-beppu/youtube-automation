"""Command adapter for Shorts uploads."""

import argparse
import json
from pathlib import Path

from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.core.errors import AutomationError
from youtube_automation.domains.uploads.shorts import ACTION_FAILED, ShortUploader
from youtube_automation.infrastructure.google.youtube import create_authenticated_youtube_clients


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YouTube Shorts uploader")
    parser.add_argument("collection")
    parser.add_argument("--short-num", type=int, default=None)
    parser.add_argument("--plan", action="store_true")
    return parser


def run(args: argparse.Namespace) -> int:
    uploader = ShortUploader(youtube_clients=create_authenticated_youtube_clients())
    collection_path = Path(args.collection)
    if not collection_path.is_absolute():
        collection_path = Path.cwd() / collection_path
    if args.plan:
        uploader.show_plan(collection_path, short_num=args.short_num)
        return 0
    result = uploader.upload_short(collection_path, short_num=args.short_num)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["action"] == ACTION_FAILED else 0


def main(argv: list[str] | None = None) -> int:
    return run_cli(
        build_parser,
        run,
        argv,
        failure_message="エラー",
        interrupt_message="中断されました",
        interrupt_exit_code=130,
        handled_errors=(AutomationError, OSError, ValueError),
    )
