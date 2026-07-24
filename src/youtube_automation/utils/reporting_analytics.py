"""Reporting API 取得 Mixin。fail-open: 取得失敗時は None を返し collector 全体は継続する。"""

from __future__ import annotations

import logging
from typing import Any

from youtube_automation.infrastructure.errors import AutomationError
from youtube_automation.utils.reporting_api import ReportingAPIClient

logger = logging.getLogger(__name__)


class ReportingAPIMixin:
    def get_reporting_impressions_summary(self, days: int = 7) -> dict[str, Any] | None:
        try:
            clients = self.youtube_clients
            client = ReportingAPIClient(clients.reporting, credentials=clients._read_handler.authenticate())
            return client.collect_impressions_summary(days=days)
        except AutomationError as e:
            logger.warning(f"Reporting API 取得失敗（続行）: {e}")
            return None
