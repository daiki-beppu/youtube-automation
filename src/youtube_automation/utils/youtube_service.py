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

import logging

from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


class ServiceRegistry:
    """YouTube API サービスのキャッシュレジストリ。

    テスト時はインスタンスを直接生成するか、reset() でキャッシュをクリアする。

    read 系（analytics / reporting / youtube_readonly）は token.readonly.json
    （write scope を含まない）を優先し、未発行時は warning ログ付きで
    token.json（全 scope）へフォールバックする（#1699）。
    """

    def __init__(self, handler=None):
        """
        Args:
            handler: YouTubeOAuthHandler インスタンス（省略時は遅延生成）。
                明示注入時は read 系もこのハンドラーを共用する（テスト・DI 向け）
        """
        self._handler = handler
        self._readonly_handler = None
        self._youtube_service = None
        self._youtube_readonly_service = None
        self._analytics_service = None
        self._reporting_service = None

    def _get_handler(self):
        if self._handler is None:
            from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler

            self._handler = YouTubeOAuthHandler()
        return self._handler

    def _get_readonly_handler(self):
        """read 系サービス用ハンドラーを返す。

        token.readonly.json 発行済みなら read-only スコープのハンドラー、
        未発行なら token.json のハンドラーへフォールバック（サイレント失敗させず
        warning で発行手順を案内する。#1699 要件 3）。
        """
        if self._readonly_handler is not None:
            return self._readonly_handler
        if self._handler is not None:
            # コンストラクタで明示注入されたハンドラーは read 系でも共用する
            self._readonly_handler = self._handler
            return self._readonly_handler

        from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler

        if YouTubeOAuthHandler.readonly_token_path() is None:
            logger.warning(
                "token.readonly.json が未発行のため token.json（全 scope）へフォールバックします。"
                "最小権限で運用するには `uv run yt-oauth --readonly` で発行してください（#1699）"
            )
            self._readonly_handler = self._get_handler()
        else:
            self._readonly_handler = YouTubeOAuthHandler.create_readonly()
        return self._readonly_handler

    @property
    def youtube(self):
        """YouTube Data API v3 サービスを返す（キャッシュ済み・全 scope）。"""
        if self._youtube_service is None:
            self._youtube_service = self._get_handler().get_youtube_service()
        return self._youtube_service

    @property
    def youtube_readonly(self):
        """YouTube Data API v3 サービスを返す（キャッシュ済み・read-only 優先）。

        list 系のみの read-only スクリプト（benchmark / channel-status 等）はこちらを使う。
        """
        if self._youtube_readonly_service is None:
            self._youtube_readonly_service = self._get_readonly_handler().get_youtube_service()
        return self._youtube_readonly_service

    @property
    def analytics(self):
        """YouTube Analytics API v2 サービスを返す（キャッシュ済み・read-only 優先）。"""
        if self._analytics_service is None:
            credentials = self._get_readonly_handler().authenticate()
            self._analytics_service = build("youtubeAnalytics", "v2", credentials=credentials)
        return self._analytics_service

    @property
    def reporting(self):
        """YouTube Reporting API v1 サービスを返す（キャッシュ済み・read-only 優先）。"""
        if self._reporting_service is None:
            credentials = self._get_readonly_handler().authenticate()
            self._reporting_service = build("youtubereporting", "v1", credentials=credentials)
        return self._reporting_service

    @property
    def credentials(self):
        """OAuth credentials を返す（全 scope）。"""
        return self._get_handler().authenticate()

    @property
    def credentials_readonly(self):
        """OAuth credentials を返す（read-only 優先。Reporting API のダウンロード等）。"""
        return self._get_readonly_handler().authenticate()

    def reset(self):
        """キャッシュをクリア（テスト用）。"""
        self._handler = None
        self._readonly_handler = None
        self._youtube_service = None
        self._youtube_readonly_service = None
        self._analytics_service = None
        self._reporting_service = None


# デフォルトのグローバルレジストリ
_default_registry = ServiceRegistry()


def _get_handler():
    """後方互換: テストの patch 対象として維持。"""
    return _default_registry._get_handler()


def get_youtube():
    """YouTube Data API v3 サービスを返す（キャッシュ済み・全 scope）。"""
    return _default_registry.youtube


def get_readonly_handler():
    """read 系用の YouTubeOAuthHandler を返す（token.readonly.json 優先・未発行は fallback）。

    サービスではなく handler 自体が必要な呼び出し元（authenticate / test_connection の
    事前実行等）向け。registry の選択ロジックとキャッシュを共有する。
    """
    return _default_registry._get_readonly_handler()


def get_youtube_readonly():
    """YouTube Data API v3 サービスを返す（キャッシュ済み・read-only 優先）。"""
    return _default_registry.youtube_readonly


def get_analytics():
    """YouTube Analytics API v2 サービスを返す（キャッシュ済み）。"""
    return _default_registry.analytics


def get_reporting():
    """YouTube Reporting API v1 サービスを返す（キャッシュ済み）。"""
    return _default_registry.reporting


def get_credentials():
    """OAuth credentials を返す（キャッシュ済み・全 scope）。"""
    return _default_registry.credentials


def get_credentials_readonly():
    """OAuth credentials を返す（キャッシュ済み・read-only 優先）。"""
    return _default_registry.credentials_readonly


def reset():
    """キャッシュをリセット（テスト用）。"""
    _default_registry.reset()
