"""dashboard 起動前に登録チャンネルの Analytics を逐次更新する。"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from youtube_automation.utils.exceptions import AutomationError

logger = logging.getLogger(__name__)


@contextmanager
def _channel_context(channel: Path) -> Iterator[None]:
    from youtube_automation.configuration import reset as reset_config
    from youtube_automation.utils.youtube_service import reset as reset_services

    previous_dir = os.environ.get("CHANNEL_DIR")
    previous_slug = os.environ.get("CHANNEL")
    os.environ["CHANNEL_DIR"] = str(channel)
    os.environ.pop("CHANNEL", None)
    reset_config()
    reset_services()
    try:
        yield
    finally:
        if previous_dir is None:
            os.environ.pop("CHANNEL_DIR", None)
        else:
            os.environ["CHANNEL_DIR"] = previous_dir
        if previous_slug is None:
            os.environ.pop("CHANNEL", None)
        else:
            os.environ["CHANNEL"] = previous_slug
        reset_config()
        reset_services()


def collect_channel_analytics(channel: Path) -> None:
    """既存 AnalyticsSystem を使って1チャンネルのstandard snapshotを保存する。"""
    from youtube_automation.scripts.analytics_system import AnalyticsSystem

    with _channel_context(channel):
        result = AnalyticsSystem().run_data_collection(days=30, depth="standard")
    if not result.get("success"):
        raise AutomationError(str(result.get("error", "Analytics refresh failed")))


def refresh_dashboard_channels(
    channels: list[Path],
    *,
    collect_channel: Callable[[Path], None] = collect_channel_analytics,
) -> dict[Path, str]:
    """全チャンネルを登録順に更新し、想定内の失敗だけをpath別に返す。"""
    errors: dict[Path, str] = {}
    for channel in channels:
        logger.info("dashboard Analytics 更新開始: %s", channel)
        try:
            collect_channel(channel)
        except (AutomationError, OSError, RuntimeError, ValueError) as exc:
            logger.error("dashboard Analytics 更新失敗: %s: %s", channel, exc)
            errors[channel] = str(exc)
        else:
            logger.info("dashboard Analytics 更新完了: %s", channel)
    return errors
