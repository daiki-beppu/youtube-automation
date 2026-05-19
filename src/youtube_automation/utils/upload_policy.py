"""アップロードに関するドメインロジック。

YouTubeUploadCore から抽出した純粋なビジネス判断。
サムネイル圧縮戦略とリトライ戦略をドメインモデルとしてカプセル化する。
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_THUMBNAIL_BYTES = 2_097_152
COMPRESSION_QUALITIES = (2, 5)
MAX_RETRY_ATTEMPTS = 5
RETRYABLE_HTTP_STATUSES = frozenset({500, 502, 503, 504})
# resumable upload の session URI が失効済みとみなすべき HTTP ステータス。
# 404 / 410 は googleapiclient が dead resumable session を通知する典型形態で、
# `RETRYABLE_HTTP_STATUSES` とは交わらない独立分岐（retry せず URI をクリアする）。
SESSION_EXPIRED_HTTP_STATUSES = frozenset({404, 410})


@dataclass(frozen=True)
class ThumbnailCompression:
    """サムネイル圧縮ワークフローの判断結果。"""

    needs_compression: bool
    qualities_to_try: tuple[int, ...] = ()

    @classmethod
    def for_file(cls, file_size: int, max_bytes: int = MAX_THUMBNAIL_BYTES) -> ThumbnailCompression:
        """ファイルサイズに基づいて圧縮戦略を決定する。"""
        if file_size <= max_bytes:
            return cls(needs_compression=False)
        return cls(needs_compression=True, qualities_to_try=COMPRESSION_QUALITIES)

    def next_quality(self, failed_qualities: set[int]) -> int | None:
        """次に試すべき圧縮品質を返す。全て試行済みなら None。"""
        for q in self.qualities_to_try:
            if q not in failed_qualities:
                return q
        return None


@dataclass(frozen=True)
class RetryDecision:
    """HTTP エラーに対するリトライ判断の結果。"""

    should_retry: bool
    delay_seconds: float = 0.0

    @classmethod
    def for_http_error(cls, status_code: int, current_attempt: int) -> RetryDecision:
        """HTTP ステータスとリトライ回数に基づいてリトライ判断を返す。"""
        if status_code not in RETRYABLE_HTTP_STATUSES:
            return cls(should_retry=False)
        if current_attempt >= MAX_RETRY_ATTEMPTS:
            return cls(should_retry=False)
        return cls(should_retry=True, delay_seconds=float(2**current_attempt))
