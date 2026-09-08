"""Reporting API 取得 Mixin。fail-open: 取得失敗時は None を返し collector 全体は継続する。"""

from __future__ import annotations

import logging

from youtube_automation.core.errors import AutomationError
from youtube_automation.domains.analytics.ports import ReportingClient

logger = logging.getLogger(__name__)


def collect_reporting_impressions(client: ReportingClient, days: int = 7) -> dict[str, object] | None:
    """Retrieve optional reporting data without aborting the other analytics queries."""
    try:
        return client.collect_impressions_summary(days=days)
    except AutomationError as error:
        logger.warning(f"Reporting API 取得失敗（続行）: {error}")
        return None


class ReportingAPIMixin:
    """Compatibility adapter for callers that still assemble collectors with mixins."""

    reporting_client: ReportingClient

    def get_reporting_impressions_summary(self, days: int = 7) -> dict[str, object] | None:
        return collect_reporting_impressions(self.reporting_client, days)
