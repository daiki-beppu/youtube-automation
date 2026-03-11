"""YouTube API サービスファクトリ（シングルトンキャッシュ）。

Usage:
    from utils.youtube_service import get_youtube, get_analytics

    youtube = get_youtube()
    analytics = get_analytics()
"""

from googleapiclient.discovery import build

_handler = None
_youtube_service = None
_analytics_service = None


def _get_handler():
    global _handler
    if _handler is None:
        from auth.oauth_handler import YouTubeOAuthHandler
        _handler = YouTubeOAuthHandler()
    return _handler


def get_youtube():
    """YouTube Data API v3 サービスを返す（キャッシュ済み）。"""
    global _youtube_service
    if _youtube_service is None:
        _youtube_service = _get_handler().get_youtube_service()
    return _youtube_service


def get_analytics():
    """YouTube Analytics API v2 サービスを返す（キャッシュ済み）。"""
    global _analytics_service
    if _analytics_service is None:
        credentials = _get_handler().authenticate()
        _analytics_service = build('youtubeAnalytics', 'v2', credentials=credentials)
    return _analytics_service


def get_credentials():
    """OAuth credentials を返す（キャッシュ済み）。"""
    return _get_handler().authenticate()


def reset():
    """キャッシュをリセット（テスト用）。"""
    global _handler, _youtube_service, _analytics_service
    _handler = None
    _youtube_service = None
    _analytics_service = None
