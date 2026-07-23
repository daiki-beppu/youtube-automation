"""責務別に分割されたチャンネル設定 API.

公開 API:
    load_config() -> ChannelConfig   # シングルトン取得（初回に glob ロード + .env ロード）
    channel_dir() -> Path            # config/channel/ を含むプロジェクトルート解決
    find_workspace_root()            # cwd 祖先から workspace root を検出
    workspace_channels()             # workspace の slug と channel dir を列挙
    select_channel()                 # CLI の明示 channel slug を初回解決へ渡す
    reset() -> None                  # シングルトン state をリセット（テスト用）
    ChannelConfig                    # 合成ルート dataclass（型ヒント用）
    CommunityDraft                   # `community_draft` セクション（型ヒント用）
    Shorts                           # `shorts` セクション（型ヒント用）
    PinnedComment                    # `pinned_comment` セクション（型ヒント用）
    Distrokid                        # `distrokid` セクション（型ヒント用）
"""

from youtube_automation.configuration.community_draft import CommunityDraft
from youtube_automation.configuration.distrokid import Distrokid
from youtube_automation.configuration.loader import (
    channel_dir,
    find_workspace_root,
    load_config,
    reset,
    select_channel,
    workspace_channels,
)
from youtube_automation.configuration.model import ChannelConfig
from youtube_automation.configuration.pinned_comment import PinnedComment
from youtube_automation.configuration.shorts import Shorts

__all__ = [
    "ChannelConfig",
    "CommunityDraft",
    "Distrokid",
    "PinnedComment",
    "Shorts",
    "channel_dir",
    "find_workspace_root",
    "load_config",
    "reset",
    "select_channel",
    "workspace_channels",
]
