"""チャンネル設定を認証表示と Google クライアント生成に組み合わせる。"""

from youtube_automation.core.errors import ConfigError
from youtube_automation.infrastructure.auth.youtube import YouTubeOAuthHandler as BaseYouTubeOAuthHandler
from youtube_automation.infrastructure.google import youtube as youtube_io


class YouTubeOAuthHandler(BaseYouTubeOAuthHandler):
    """設定のチャンネル名を表示し、設定不備でも認証を継続する。"""

    def _channel_label(self) -> str:
        try:
            from youtube_automation.configuration import load_config

            return load_config().meta.channel_short
        except ConfigError:
            return super()._channel_label()


def create_authenticated_youtube_clients() -> youtube_io.YouTubeClients:
    return youtube_io.YouTubeClients(full_handler=YouTubeOAuthHandler())


def create_readonly_youtube_clients() -> youtube_io.YouTubeClients:
    return youtube_io.YouTubeClients(readonly_handler=YouTubeOAuthHandler.create_readonly(interactive=False))
