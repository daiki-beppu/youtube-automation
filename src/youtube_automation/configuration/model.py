"""`ChannelConfig` 合成ルート dataclass."""

from __future__ import annotations

from dataclasses import dataclass

from youtube_automation.configuration.analytics import Analytics
from youtube_automation.configuration.audio import Audio
from youtube_automation.configuration.comments import Comments
from youtube_automation.configuration.community_draft import CommunityDraft
from youtube_automation.configuration.content import Content
from youtube_automation.configuration.distrokid import Distrokid
from youtube_automation.configuration.localizations import Localizations
from youtube_automation.configuration.meta import ChannelMeta
from youtube_automation.configuration.pinned_comment import PinnedComment
from youtube_automation.configuration.playlists import Playlists
from youtube_automation.configuration.shorts import Shorts
from youtube_automation.configuration.workflow import Workflow
from youtube_automation.configuration.youtube import YoutubeSection


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
    community_draft: CommunityDraft
    pinned_comment: PinnedComment
    distrokid: Distrokid
