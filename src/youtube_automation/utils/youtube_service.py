"""YouTube API サービスファクトリ（ServiceRegistry）。

ServiceRegistry クラスでサービスインスタンスをキャッシュ管理する。
デフォルトのグローバルレジストリ経由でモジュールレベル関数も提供（後方互換）。

Usage:
    # モジュールレベル関数（従来互換）
    from youtube_automation.utils.youtube_service import get_youtube, get_analytics

    youtube = get_youtube()
    analytics = get_analytics()

    # クラスベース（テスト・DI 向け）
    registry = ServiceRegistry()
    youtube = registry.youtube
    analytics = registry.analytics
"""

from googleapiclient.discovery import build


class ServiceRegistry:
    """YouTube API サービスのキャッシュレジストリ。

    テスト時はインスタンスを直接生成するか、reset() でキャッシュをクリアする。
    """

    def __init__(self, handler=None):
        """
        Args:
            handler: YouTubeOAuthHandler インスタンス（省略時は遅延生成）
        """
        self._handler = handler
        self._youtube_service = None
        self._analytics_service = None
        self._reporting_service = None

    def _get_handler(self):
        if self._handler is None:
            from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler

            self._handler = YouTubeOAuthHandler()
        return self._handler

    @property
    def youtube(self):
        """YouTube Data API v3 サービスを返す（キャッシュ済み）。"""
        if self._youtube_service is None:
            self._youtube_service = self._get_handler().get_youtube_service()
        return self._youtube_service

    @property
    def analytics(self):
        """YouTube Analytics API v2 サービスを返す（キャッシュ済み）。"""
        if self._analytics_service is None:
            credentials = self._get_handler().authenticate()
            self._analytics_service = build("youtubeAnalytics", "v2", credentials=credentials)
        return self._analytics_service

    @property
    def reporting(self):
        """YouTube Reporting API v1 サービスを返す（キャッシュ済み）。"""
        if self._reporting_service is None:
            credentials = self._get_handler().authenticate()
            self._reporting_service = build("youtubereporting", "v1", credentials=credentials)
        return self._reporting_service

    @property
    def credentials(self):
        """OAuth credentials を返す。"""
        return self._get_handler().authenticate()

    def reset(self):
        """キャッシュをクリア（テスト用）。"""
        self._handler = None
        self._youtube_service = None
        self._analytics_service = None
        self._reporting_service = None


# デフォルトのグローバルレジストリ
_default_registry = ServiceRegistry()


def _get_handler():
    """後方互換: テストの patch 対象として維持。"""
    return _default_registry._get_handler()


def get_youtube():
    """YouTube Data API v3 サービスを返す（キャッシュ済み）。"""
    return _default_registry.youtube


def get_analytics():
    """YouTube Analytics API v2 サービスを返す（キャッシュ済み）。"""
    return _default_registry.analytics


def get_reporting():
    """YouTube Reporting API v1 サービスを返す（キャッシュ済み）。"""
    return _default_registry.reporting


def get_credentials():
    """OAuth credentials を返す（キャッシュ済み）。"""
    return _default_registry.credentials


def reset():
    """キャッシュをリセット（テスト用）。"""
    _default_registry.reset()
