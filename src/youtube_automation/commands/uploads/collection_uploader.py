"""Command adapter for collection uploads."""

import argparse
import logging

from youtube_automation.application.pipeline_notifications import PipelineNotificationBridge
from youtube_automation.commands._shared.cli_harness import run_cli
from youtube_automation.configuration import load_config
from youtube_automation.core.errors import AutomationError
from youtube_automation.domains.notifications import NotificationEventKind
from youtube_automation.domains.uploads.collection import (
    ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED,
    ACTION_COMPLETE_COLLECTION_UPLOADED,
    CollectionUploader,
)
from youtube_automation.infrastructure.google.youtube import create_authenticated_youtube_clients
from youtube_automation.infrastructure.notifications.discord import create_discord_notification_sink


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Complete Collection を YouTube へアップロードする")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--daemon", "-d", action="store_true")
    parser.add_argument("--collection", "-c")
    parser.add_argument(
        "--config",
        help="schedule_config.json のファイルパス（既定: <channel_dir>/config/schedule_config.json）",
    )
    parser.add_argument(
        "--allow-duration-outside-target",
        action="store_true",
        help="operator 判断で config/channel/audio.json の目標尺外を明示許可する",
    )
    return parser


def run(args: argparse.Namespace) -> None:
    uploader = CollectionUploader(
        config_path=args.config,
        youtube_clients=create_authenticated_youtube_clients(),
        allow_duration_outside_target=getattr(args, "allow_duration_outside_target", False),
    )
    if args.daemon:
        uploader.run_automated_schedule()
        return
    target = uploader.find_collection(args.collection)
    if target:
        if args.status:
            uploader.show_status(target)
            return
        notifications = PipelineNotificationBridge(create_discord_notification_sink())
        channel = load_config().meta.channel_short

        def notify_abort(stage: str) -> None:
            notifications.emit(
                NotificationEventKind.FAIL_CLOSED_ABORTED,
                channel=channel,
                collection=target.name,
                stage=stage,
            )

        if args.plan:
            # show_plan は表示専用なので、ドライランでも実行時と同じ検査集合を
            # 通すために upload 境界の preflight を明示的に依頼する。
            try:
                uploader.preflight_check(target)
            except (AutomationError, OSError, ValueError):
                notify_abort("upload-preflight")
                raise
            uploader.show_plan(target)
        else:
            # この try は preflight だけでなく execute_next_step 全体（実アップロード /
            # tracking I/O / quota 判定 / プレイリスト割当）を囲むため、stage は
            # preflight 固定ではなく実行系を表す名前にする。
            try:
                result = uploader.execute_next_step(target)
            except (AutomationError, OSError, ValueError):
                notify_abort("upload-execution")
                raise
            action = result.get("action")
            if action == ACTION_COMPLETE_COLLECTION_UPLOADED:
                notifications.emit(
                    NotificationEventKind.PUBLISH_COMPLETED,
                    channel=channel,
                    collection=target.name,
                    stage="youtube-publish",
                )
            elif action == ACTION_COMPLETE_COLLECTION_QUOTA_EXHAUSTED:
                notifications.emit(
                    NotificationEventKind.GUARD_EXCEEDED,
                    channel=channel,
                    collection=target.name,
                    stage="upload-quota",
                )


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
