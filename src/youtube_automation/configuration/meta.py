"""チャンネルメタ情報とブランディング設定の責務別 dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Branding:
    """`youtube_channel` セクション。YouTube チャンネル本体設定（任意セクション）."""

    description: str = ""
    keywords: list[str] = field(default_factory=list)
    country: str = ""
    default_language: str = ""
    unsubscribed_trailer: str = ""
    made_for_kids: bool | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> "Branding":
        if not data:
            return cls()
        return cls(
            description=data.get("description", ""),
            keywords=list(data.get("keywords", [])),
            country=data.get("country", ""),
            default_language=data.get("default_language", ""),
            unsubscribed_trailer=data.get("unsubscribed_trailer", ""),
            made_for_kids=data.get("made_for_kids"),
        )

    def as_api_dict(self) -> dict:
        """YouTube API / yt-channel-settings が扱う dict 形式に戻す（未設定キーは省略）."""
        out: dict = {}
        if self.description:
            out["description"] = self.description
        if self.keywords:
            out["keywords"] = list(self.keywords)
        if self.country:
            out["country"] = self.country
        if self.default_language:
            out["default_language"] = self.default_language
        if self.unsubscribed_trailer:
            out["unsubscribed_trailer"] = self.unsubscribed_trailer
        if self.made_for_kids is not None:
            out["made_for_kids"] = self.made_for_kids
        return out


@dataclass(frozen=True)
class ChannelMeta:
    """`channel` セクション + `youtube_channel` セクション（Branding）の合成."""

    channel_name: str
    channel_short: str
    youtube_handle: str
    channel_url: str
    core_message: str = ""
    cta_subscribe: str = ""
    tagline: str = ""
    # YouTube チャンネル ID（`UC...`）。OAuth トークン取り違え防止の照合に使う (#561)。
    # 未設定（空文字）のチャンネルでは照合をスキップする。
    channel_id: str = ""
    branding: Branding = field(default_factory=Branding)
