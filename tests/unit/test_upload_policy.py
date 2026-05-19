"""upload_policy のユニットテスト（Khorikov 出力ベース）

ドメインモデルの純粋ロジックを検証。mock ゼロ。
"""

import pytest

from youtube_automation.utils.upload_policy import (
    MAX_RETRY_ATTEMPTS,
    MAX_THUMBNAIL_BYTES,
    RetryDecision,
    ThumbnailCompression,
)

# ---------------------------------------------------------------------------
# ThumbnailCompression: サムネイル圧縮戦略
# ---------------------------------------------------------------------------


class TestThumbnailCompression:
    def test_skips_compression_for_small_file(self):
        result = ThumbnailCompression.for_file(1000)
        assert result.needs_compression is False
        assert result.qualities_to_try == ()

    def test_skips_compression_at_exact_limit(self):
        result = ThumbnailCompression.for_file(MAX_THUMBNAIL_BYTES)
        assert result.needs_compression is False

    def test_requires_compression_for_oversized_file(self):
        result = ThumbnailCompression.for_file(3_000_000)
        assert result.needs_compression is True
        assert result.qualities_to_try == (2, 5)

    def test_suggests_next_quality_in_order(self):
        comp = ThumbnailCompression.for_file(3_000_000)
        assert comp.next_quality(failed_qualities=set()) == 2
        assert comp.next_quality(failed_qualities={2}) == 5

    def test_returns_none_when_all_qualities_exhausted(self):
        comp = ThumbnailCompression.for_file(3_000_000)
        assert comp.next_quality(failed_qualities={2, 5}) is None

    def test_respects_custom_max_bytes(self):
        result = ThumbnailCompression.for_file(500, max_bytes=100)
        assert result.needs_compression is True


# ---------------------------------------------------------------------------
# RetryDecision: リトライ戦略
# ---------------------------------------------------------------------------


class TestRetryDecision:
    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_retries_on_server_error(self, status):
        decision = RetryDecision.for_http_error(status, current_attempt=0)
        assert decision.should_retry is True
        assert decision.delay_seconds > 0

    @pytest.mark.parametrize("status", [400, 403, 404])
    def test_gives_up_on_client_error(self, status):
        decision = RetryDecision.for_http_error(status, current_attempt=0)
        assert decision.should_retry is False

    def test_gives_up_after_max_attempts(self):
        decision = RetryDecision.for_http_error(503, current_attempt=MAX_RETRY_ATTEMPTS)
        assert decision.should_retry is False

    def test_retries_just_before_max_attempts(self):
        decision = RetryDecision.for_http_error(503, current_attempt=MAX_RETRY_ATTEMPTS - 1)
        assert decision.should_retry is True

    @pytest.mark.parametrize(
        "attempt, expected_delay",
        [
            (0, 1.0),
            (1, 2.0),
            (2, 4.0),
            (3, 8.0),
        ],
    )
    def test_applies_exponential_backoff(self, attempt, expected_delay):
        decision = RetryDecision.for_http_error(503, current_attempt=attempt)
        assert decision.delay_seconds == expected_delay

    def test_retries_on_rate_limit(self):
        """429 (Too Many Requests / quota) は再試行対象。"""
        decision = RetryDecision.for_http_error(429, current_attempt=0)
        assert decision.should_retry is True
        assert decision.delay_seconds > 0

    def test_respects_retry_after_header(self):
        """Retry-After で与えられた秒数をそのまま delay として採用する。"""
        decision = RetryDecision.for_http_error(429, current_attempt=0, retry_after_seconds=10.0)
        assert decision.should_retry is True
        assert decision.delay_seconds == 10.0

    def test_falls_back_to_exponential_when_no_retry_after(self):
        """Retry-After が無ければ ``2 ** attempt`` の指数 backoff。"""
        decision = RetryDecision.for_http_error(429, current_attempt=2)
        assert decision.should_retry is True
        assert decision.delay_seconds == 4.0

    def test_retry_after_applies_to_5xx_too(self):
        """Retry-After は 5xx にも一律適用される（指数 backoff を上書き）。"""
        decision = RetryDecision.for_http_error(503, current_attempt=0, retry_after_seconds=7.0)
        assert decision.should_retry is True
        assert decision.delay_seconds == 7.0

    def test_falls_back_to_exponential_when_retry_after_non_positive(self):
        """Retry-After が 0 以下なら指数 backoff にフォールバック。"""
        decision = RetryDecision.for_http_error(429, current_attempt=1, retry_after_seconds=0.0)
        assert decision.should_retry is True
        assert decision.delay_seconds == 2.0

    def test_gives_up_on_rate_limit_after_max_attempts(self):
        """429 でも MAX_RETRY_ATTEMPTS を超えれば諦める。"""
        decision = RetryDecision.for_http_error(429, current_attempt=MAX_RETRY_ATTEMPTS)
        assert decision.should_retry is False
