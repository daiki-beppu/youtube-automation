"""ドメイン固有例外クラス。

アプリケーション全体で一貫したエラーハンドリングを提供する。
"""

import json


class AutomationError(Exception):
    """youtube-channels-automation の基底例外"""


class ConfigError(AutomationError):
    """設定ファイルの読み込み・バリデーションエラー

    - config/channel/*.json の必須キー欠落
    - 設定ファイルが見つからない
    - JSON パースエラー
    """


class YouTubeAPIError(AutomationError):
    """YouTube Data API / Analytics API の呼び出しエラー

    - クォータ超過
    - 認証失敗
    - レスポンス不正
    """

    def __init__(self, message: str, status_code: int | None = None, reason: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason

    @classmethod
    def from_http_error(cls, error, context: str) -> "YouTubeAPIError":
        status = getattr(getattr(error, "resp", None), "status", None)
        return cls(
            f"{context}: {error}",
            status_code=int(status) if status is not None else None,
            reason=_http_error_reason(error),
        )


class QuotaExhaustedError(YouTubeAPIError):
    """quota 切れ / レート制限超過（HTTP 429）。

    時間をおいて再実行することで resume 可能であることを呼び出し側に明示する。
    ``retry_after_seconds`` は Retry-After header から抽出した推奨待機秒数（取得失敗時 None）。
    """

    def __init__(self, message: str, retry_after_seconds: float | None = None):
        super().__init__(message, status_code=429)
        self.retry_after_seconds = retry_after_seconds


class AuthError(AutomationError):
    """OAuth 2.0 認証関連のエラー

    - client_secrets.json の読み込み失敗
    - run_local_server 経路の認証失敗
    - GoogleAuthError 系の取りまとめ
    """


class ValidationError(AutomationError):
    """入力データのバリデーションエラー

    - メタデータの不正値
    - ファイルパスの不正
    - コレクション名の不正
    """


class UploadError(AutomationError):
    """動画・サムネイルアップロードの失敗

    - リトライ上限到達
    - ファイル不在
    - サムネイル圧縮失敗
    """


class GeneratorError(AutomationError):
    """返信生成バックエンドの失敗（API エラー・レスポンス不正等）"""


class DiscoveryRegistryError(AutomationError):
    """ローカル server discovery registry の所有・容量契約エラー。"""


def _http_error_reason(error) -> str | None:
    content = getattr(error, "content", b"")
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return None
    return _payload_reason(payload)


def _payload_reason(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    errors = error.get("errors")
    if isinstance(errors, list):
        for item in errors:
            if isinstance(item, dict) and isinstance(item.get("reason"), str):
                return item["reason"]
    reason = error.get("reason")
    return reason if isinstance(reason, str) else None
