"""
Analytics Mixin が依存するインターフェース定義

YouTubeAnalyticsCollector の 5 つの Mixin が暗黙的に参照する
属性・メソッドを Protocol で明示化する。

各 Mixin は runtime_checkable な AnalyticsBase を通じて
必要な属性の存在を保証する。
"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class AnalyticsBase(Protocol):
    """Mixin が期待する親クラスのインターフェース

    YouTubeAnalyticsCollector はこの Protocol を満たす必要がある。
    各 Mixin メソッドが暗黙的に参照する属性・メソッドを明示化。
    """

    youtube_service: Any
    analytics_service: Any
    channel_id: str | None

    def initialize(self) -> None: ...

    def _get_video_details(self, video_ids: List[str]) -> Dict: ...

    def get_all_channel_videos(self) -> List[Dict]: ...

    def get_scheduled_video_count(self) -> int: ...

    def get_video_analytics_by_id(self, video_id: str, start_date: str, end_date: str) -> Dict: ...

    def get_video_analytics(self, start_date: str, end_date: str) -> List[Dict]: ...

    def get_recent_videos(self, days: int = 30) -> List[Dict]: ...
