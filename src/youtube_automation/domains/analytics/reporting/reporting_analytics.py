"""Reporting API 取得 Mixin。fail-open: 取得失敗時は None を返し collector 全体は継続する。"""

from __future__ import annotations

import logging

from youtube_automation.domains.analytics.ports import ReportingClient
from youtube_automation.utils.exceptions import AutomationError

logger = logging.getLogger(__name__)


class ReportingAPIMixin:
    reporting_client: ReportingClient

    def get_reporting_impressions_summary(self, days: int = 7) -> dict[str, object] | None:
        try:
            return self.reporting_client.collect_impressions_summary(days=days)
        except AutomationError as e:
            logger.warning(f"Reporting API 取得失敗（続行）: {e}")
            return None
