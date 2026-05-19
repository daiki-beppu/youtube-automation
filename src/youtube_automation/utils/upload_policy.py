"""アップロードに関するドメインロジック。

YouTubeUploadCore から抽出した純粋なビジネス判断。
サムネイル圧縮戦略とリトライ戦略をドメインモデルとしてカプセル化する。
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_THUMBNAIL_BYTES = 2_097_152
COMPRESSION_QUALITIES = (2, 5)
MAX_RETRY_ATTEMPTS = 5
# 429 (Too Many Requests / quota) も再試行対象。Retry-After header があれば尊重し、
# なければ指数 backoff にフォールバックする。
RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})


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
    def for_http_error(
        cls,
        status_code: int,
        current_attempt: int,
        retry_after_seconds: float | None = None,
    ) -> RetryDecision:
        """HTTP ステータスとリトライ回数に基づいてリトライ判断を返す。

        ``retry_after_seconds`` は Retry-After header から抽出した待機秒数。
        正の値が与えられた場合はそれを優先し、なければ ``2 ** current_attempt`` の
        指数 backoff にフォールバックする。
        """
        if status_code not in RETRYABLE_HTTP_STATUSES:
            return cls(should_retry=False)
        if current_attempt >= MAX_RETRY_ATTEMPTS:
            return cls(should_retry=False)
        if retry_after_seconds is not None and retry_after_seconds > 0:
            return cls(should_retry=True, delay_seconds=float(retry_after_seconds))
        return cls(should_retry=True, delay_seconds=float(2**current_attempt))
