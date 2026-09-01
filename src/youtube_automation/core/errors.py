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


class ChannelRegistryError(ConfigError):
    """所有チャンネル registry の読み込み・バリデーションエラー。"""


class DashboardChannelNotFoundError(AutomationError):
    """Dashboard read model に要求されたチャンネルが存在しない。"""


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


class DocumentValidationError(ValidationError):
    """リポジトリ所有 JSON Schema に対する文書検証エラー。"""


class DocumentRenderError(ValidationError):
    """検証済み構造化文書の HTML 生成・検証エラー。"""


class DocumentPairMismatchError(DocumentRenderError):
    """公開済み HTML が JSON から再生成した期待 HTML と一致しない（pair 陳腐化）。"""


class BrowserOpenError(AutomationError):
    """生成済みローカル文書を既定ブラウザで開けない。"""


class ReviewError(AutomationError):
    """成果物review lifecycleの再実行可能な失敗。"""


class ReviewSelectionError(ReviewError):
    """loopback brokerへ送られたselectionが契約を満たさない。"""


class DocumentMigrationError(ValidationError):
    """skill 生成 Markdown から構造化文書への状態遷移エラー。"""


class UploadError(AutomationError):
    """動画・サムネイルアップロードの失敗

    - リトライ上限到達
    - ファイル不在
    - サムネイル圧縮失敗
    """


class UploadJournalError(UploadError):
    """upload journal の読み書き・状態契約エラー。"""


class UploadJournalCorruptError(UploadJournalError):
    """破損 journal が quarantine され、再開可否を判断できない。"""


class UploadJournalSaveError(UploadJournalError):
    """upload journal の永続化に失敗した。"""


class GeneratorError(AutomationError):
    """返信生成バックエンドの失敗（API エラー・レスポンス不正等）"""


class DiscoveryRegistryError(AutomationError):
    """ローカル server discovery registry の所有・容量契約エラー。"""


class WorkflowStateError(AutomationError):
    """workflow-state.json の読み取り・検証・永続化エラー。"""


class WorkflowStateSectionTypeError(WorkflowStateError):
    """workflow-state.json の section が object でないことを型で識別する例外。"""

    def __init__(self, section: str) -> None:
        super().__init__(f"workflow-state.json::{section} must be an object")
        self.section = section


class MediaStoreError(AutomationError):
    """境界メディアの転送・完全性検証エラー。"""


class MediaHandoffNotFoundError(MediaStoreError):
    """完了マーカーが無く、受け渡し物が未完成または存在しない。"""


class StateSyncError(AutomationError):
    """Git制御面stateのpull / commit / push同期エラー。"""


class ResourceLimitError(AutomationError):
    """runner開始前の容量・費用・実行量上限エラー。"""


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
