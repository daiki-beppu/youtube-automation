"""
Analytics Mixin が依存するインターフェース定義

YouTubeAnalyticsCollector の 5 つの Mixin が暗黙的に参照する
属性・メソッドを Protocol で明示化する。
"""

from __future__ import annotations

from typing import Any, Protocol


class AnalyticsBase(Protocol):
    """Mixin が期待する親クラスのインターフェース"""

    youtube_service: Any
    analytics_service: Any
    channel_id: str | None

    def initialize(self) -> None: ...
