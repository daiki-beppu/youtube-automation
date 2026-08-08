"""dashboard 起動前に登録チャンネルの Analytics を逐次更新する。"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from youtube_automation.core.errors import AutomationError
from youtube_automation.infrastructure.analytics.dashboard_publications import (
    build_dashboard_publications,
    load_dashboard_publications,
    load_fresh_dashboard_publications,
    save_dashboard_publications,
    with_dashboard_publication_error,
)

logger = logging.getLogger(__name__)
_PUBLICATION_REFRESH_ERROR_CODE = "publication_refresh_failed"


class _AnalyticsCollector(Protocol):
    def get_all_channel_videos(self) -> list[dict[str, object]]: ...


class _AnalyticsSystem(Protocol):
    collector: _AnalyticsCollector

    def run_data_collection(self, *, days: int, depth: str) -> dict[str, object]: ...


@contextmanager
def _channel_context(channel: Path) -> Iterator[None]:
    from youtube_automation.configuration import reset as reset_config

    previous_dir = os.environ.get("CHANNEL_DIR")
    previous_slug = os.environ.get("CHANNEL")
    os.environ["CHANNEL_DIR"] = str(channel)
    os.environ.pop("CHANNEL", None)
    reset_config()
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


def collect_channel_analytics(
    channel: Path,
    analytics_system_factory: Callable[[], _AnalyticsSystem],
    *,
    force_publication_refresh: bool = False,
) -> None:
    """同じ AnalyticsSystem で standard snapshot と公開履歴を保存する。"""
    from youtube_automation.configuration import load_config

    with _channel_context(channel):
        system = analytics_system_factory()
        result = system.run_data_collection(days=30, depth="standard")
        if not result.get("success"):
            raise AutomationError(str(result.get("error", "Analytics refresh failed")))

        publication_path = channel / "data" / "dashboard_publications.json"
        fetched_at = datetime.now(UTC)
        if (
            not force_publication_refresh
            and load_fresh_dashboard_publications(publication_path, now=fetched_at) is not None
        ):
            return

        timezone = load_config().youtube.api.default_publish_timezone
        try:
            published_at_values: list[str] = []
            for video in system.collector.get_all_channel_videos():
                published_at = video.get("published_at")
                if not isinstance(published_at, str):
                    raise ValueError("動画の published_at は ISO 8601 文字列でなければなりません")
                published_at_values.append(published_at)

            payload = build_dashboard_publications(
                published_at_values,
                timezone=timezone,
                fetched_at=fetched_at,
            )
        except (AutomationError, OSError, RuntimeError, ValueError) as exc:
            cached_payload = load_dashboard_publications(publication_path)
            if cached_payload is None:
                raise
            payload = with_dashboard_publication_error(
                cached_payload,
                code=_PUBLICATION_REFRESH_ERROR_CODE,
                message=str(exc),
                attempted_at=fetched_at,
            )
        save_dashboard_publications(publication_path, payload)


def refresh_dashboard_channels(
    channels: list[Path],
    *,
    collect_channel: Callable[[Path], None],
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
