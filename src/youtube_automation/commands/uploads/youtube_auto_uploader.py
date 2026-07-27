"""Command adapter for automatic uploads."""

import argparse
import logging

from youtube_automation.commands.uploads._upload_cli_error_boundary import run_upload_cli
from youtube_automation.domains.uploads.youtube import YouTubeAutoUploader
from youtube_automation.infrastructure.google.youtube import create_authenticated_youtube_clients


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    def upload() -> None:
        parser = argparse.ArgumentParser(description="collection の動画を YouTube へ自動アップロードする")
        parser.add_argument("--collection", "-c")
        parser.add_argument("--batch", "-b", action="store_true")
        parser.add_argument("--status", "-s", nargs="+", default=["ready"])
        args = parser.parse_args()
        uploader = YouTubeAutoUploader(youtube_clients=create_authenticated_youtube_clients())
        uploader.initialize()
        if args.collection:
            uploader.upload_collection(args.collection)
        elif args.batch:
            uploader.process_collections_directory(args.status)
        else:
            print("使用法:")
            print("  単一コレクション: python youtube_auto_uploader.py -c path/to/collection")
            print("  一括処理: python youtube_auto_uploader.py --batch")

    run_upload_cli(
        upload,
        failure_message="エラー",
        interrupt_message="ユーザーによって中断されました",
        interrupt_exit_code=None,
    )
