"""``config/schedule_config.json`` の解決済み設定."""

from __future__ import annotations

from dataclasses import dataclass, field
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ScheduleConfig:
    """予約投稿とアップロード運用で利用する解決済み設定."""

    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo("Asia/Tokyo"))
    publish_time: str = "10:00"
    cadence: tuple[str, ...] = ()
    scheduling_enabled: bool = False
    scheduling_explicitly_disabled: bool = False
    category_id: str = "10"
    auto_create_playlist: bool = True
    max_retries: int = 3
    retry_delay_seconds: int = 300
    auto_move_to_live: bool = True
    backup_before_move: bool = False
    watch_ready_directory: bool = True
    discord_webhook_url: str = ""
    email_notifications: bool = False
    terminal_notifications: bool = True
    upload_quota_per_day: int = 6
    uploads_per_batch: int = 5
    concurrent_uploads: int = 1
    delay_between_uploads: int = 5
