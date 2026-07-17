"""Reporting API 取得 Mixin。fail-open: 取得失敗時は None を返し collector 全体は継続する。"""

from __future__ import annotations

import logging
from typing import Any

from youtube_automation.utils.exceptions import AutomationError
from youtube_automation.utils.reporting_api import ReportingAPIClient
from youtube_automation.utils.youtube_service import get_credentials_readonly, get_reporting

logger = logging.getLogger(__name__)


class ReportingAPIMixin:
    def get_reporting_impressions_summary(self, days: int = 7) -> dict[str, Any] | None:
        try:
            client = ReportingAPIClient(get_reporting(), credentials=get_credentials_readonly())
            return client.collect_impressions_summary(days=days)
        except AutomationError as e:
            logger.warning(f"Reporting API 取得失敗（続行）: {e}")
            return None
