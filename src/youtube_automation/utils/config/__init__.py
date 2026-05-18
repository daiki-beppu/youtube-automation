"""責務別に分割されたチャンネル設定 API.

公開 API:
    load_config() -> ChannelConfig   # シングルトン取得（初回に glob ロード + .env ロード）
    channel_dir() -> Path            # チャンネルディレクトリ解決
    reset() -> None                  # シングルトン state をリセット（テスト用）
    ChannelConfig                    # 合成ルート dataclass（型ヒント用）
    Shorts                           # `shorts` セクション（型ヒント用）
"""

from youtube_automation.utils.config.config import ChannelConfig
from youtube_automation.utils.config.loader import channel_dir, load_config, reset
from youtube_automation.utils.config.shorts import Shorts

__all__ = ["ChannelConfig", "Shorts", "channel_dir", "load_config", "reset"]
