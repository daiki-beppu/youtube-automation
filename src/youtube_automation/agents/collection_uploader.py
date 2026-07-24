"""Command adapter for collection uploads."""

import argparse
import logging

from youtube_automation.agents._upload_cli_error_boundary import run_upload_cli
from youtube_automation.configuration import load_config
from youtube_automation.domains.uploads.collection import CollectionUploader
from youtube_automation.infrastructure.google.youtube import create_authenticated_youtube_clients


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    def upload() -> None:
        config = load_config()
        parser = argparse.ArgumentParser(description=f"{config.meta.channel_short} Collection Uploader")
        parser.add_argument("--status", action="store_true")
        parser.add_argument("--plan", action="store_true")
        parser.add_argument("--daemon", "-d", action="store_true")
        parser.add_argument("--collection", "-c")
        parser.add_argument("--config")
        args = parser.parse_args()
        uploader = CollectionUploader(
            config_path=args.config,
            youtube_clients=create_authenticated_youtube_clients(),
        )
        if args.daemon:
            uploader.run_automated_schedule()
        else:
            target = uploader.find_collection(args.collection)
            if target:
                if not args.status:
                    uploader.ensure_upload_preflight(target)
                action = (
                    uploader.show_status
                    if args.status
                    else uploader.show_plan
                    if args.plan
                    else uploader.execute_next_step
                )
                action(target)

    run_upload_cli(
        upload,
        failure_message="エラー",
        interrupt_message="処理が中断されました",
        interrupt_exit_code=None,
    )
