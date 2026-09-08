"""責務別に分割されたチャンネル設定 API.

公開 API:
    load_config() -> ChannelConfig   # シングルトン取得（初回に glob ロード + .env ロード）
    load_schedule_config()           # config/channel/schedule.json の型付きローダー
    channel_dir() -> Path            # config/channel/ を含むプロジェクトルート解決
    reset() -> None                  # シングルトン state をリセット（テスト用）
    ChannelConfig                    # 合成ルート dataclass（型ヒント用）
    CommunityDraft                   # `community_draft` セクション（型ヒント用）
    Shorts                           # `shorts` セクション（型ヒント用）
    PinnedComment                    # `pinned_comment` セクション（型ヒント用）
    Distrokid                        # `distrokid` セクション（型ヒント用）
    ScheduleConfig                   # `schedule` セクション（型ヒント用）
"""

from youtube_automation.configuration.community_draft import CommunityDraft
from youtube_automation.configuration.distrokid import Distrokid
from youtube_automation.configuration.loader import load_config, load_schedule_config, reset
from youtube_automation.configuration.model import ChannelConfig
from youtube_automation.configuration.pinned_comment import PinnedComment
from youtube_automation.configuration.schedule import ScheduleConfig
from youtube_automation.configuration.shorts import Shorts
from youtube_automation.core.channel_context import channel_dir

__all__ = [
    "ChannelConfig",
    "CommunityDraft",
    "Distrokid",
    "PinnedComment",
    "ScheduleConfig",
    "Shorts",
    "channel_dir",
    "load_config",
    "load_schedule_config",
    "reset",
]
