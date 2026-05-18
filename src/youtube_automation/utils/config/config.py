"""`ChannelConfig` 合成ルート dataclass."""

from __future__ import annotations

from dataclasses import dataclass

from youtube_automation.utils.config.analytics import Analytics
from youtube_automation.utils.config.audio import Audio
from youtube_automation.utils.config.comments import Comments
from youtube_automation.utils.config.content import Content
from youtube_automation.utils.config.localizations import Localizations
from youtube_automation.utils.config.meta import ChannelMeta
from youtube_automation.utils.config.playlists import Playlists
from youtube_automation.utils.config.shorts import Shorts
from youtube_automation.utils.config.workflow import Workflow
from youtube_automation.utils.config.youtube import YoutubeSection


@dataclass(frozen=True)
class ChannelConfig:
    """チャンネル設定の合成ルート（責務別ネームスペースでアクセスする）."""

    meta: ChannelMeta
    content: Content
    youtube: YoutubeSection
    analytics: Analytics
    playlists: Playlists
    workflow: Workflow
    shorts: Shorts
    audio: Audio
    localizations: Localizations
    comments: Comments
