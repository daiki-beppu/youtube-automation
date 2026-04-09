"""ドメイン固有例外クラス。

アプリケーション全体で一貫したエラーハンドリングを提供する。
"""


class AutomationError(Exception):
    """youtube-channels-automation の基底例外"""


class ConfigError(AutomationError):
    """設定ファイルの読み込み・バリデーションエラー

    - channel_config.json の必須キー欠落
    - 設定ファイルが見つからない
    - JSON パースエラー
    """


class YouTubeAPIError(AutomationError):
    """YouTube Data API / Analytics API の呼び出しエラー

    - クォータ超過
    - 認証失敗
    - レスポンス不正
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


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
