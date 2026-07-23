"""Retry boundary for Google API requests."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, Protocol, TypeVar

from googleapiclient.errors import HttpError
from httplib2 import HttpLib2Error

from youtube_automation.utils.exceptions import YouTubeAPIError

P = ParamSpec("P")
T = TypeVar("T")


class ExecutableRequest(Protocol[T]):
    def execute(self) -> T: ...


_MAX_ATTEMPTS = 3

# テストから monkeypatch で差し替えられるモジュールスコープのシーム
# （time.sleep / random.uniform をグローバルに patch せず retry 経路だけ無効化できる）
_DEFAULT_SLEEP: Callable[[float], None] = time.sleep
_DEFAULT_JITTER: Callable[[float, float], float] = random.uniform
QUOTA_REASONS = {
    "dailyLimitExceeded",
    "quotaExceeded",
    "rateLimitExceeded",
    "userRateLimitExceeded",
}
# 後方互換: モジュール内の旧 private 名を参照するコードを壊さない。
_QUOTA_REASONS = QUOTA_REASONS


def _is_retryable(error: HttpError) -> bool:
    converted = YouTubeAPIError.from_http_error(error, "YouTube API request failed")
    status = converted.status_code
    return (
        status == 429
        or (status is not None and 500 <= status < 600)
        or (status == 403 and converted.reason in QUOTA_REASONS)
    )


def retry_youtube_api(
    context: str,
    *,
    sleep: Callable[[float], None] | None = None,
    jitter: Callable[[float, float], float] | None = None,
    on_attempt: Callable[[], None] | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Retry transient Google API failures and expose failures as domain errors."""
    sleep = sleep or _DEFAULT_SLEEP
    jitter = jitter or _DEFAULT_JITTER

    def decorate(operation: Callable[P, T]) -> Callable[P, T]:
        @wraps(operation)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            for attempt in range(_MAX_ATTEMPTS):
                try:
                    return operation(*args, **kwargs)
                except HttpError as error:
                    if not _is_retryable(error) or attempt == _MAX_ATTEMPTS - 1:
                        raise YouTubeAPIError.from_http_error(error, context) from error
                except (HttpLib2Error, OSError) as error:
                    if attempt == _MAX_ATTEMPTS - 1:
                        raise YouTubeAPIError(f"{context}: {error}") from error
                finally:
                    if on_attempt is not None:
                        on_attempt()

                delay = 2**attempt
                sleep(jitter(delay, delay * 2))

            raise AssertionError("retry loop exited unexpectedly")

        return wrapped

    return decorate


def execute_with_retry(
    request: ExecutableRequest[T],
    context: str,
    *,
    sleep: Callable[[float], None] | None = None,
    jitter: Callable[[float, float], float] | None = None,
    on_attempt: Callable[[], None] | None = None,
) -> T:
    """Execute one Google API request through the shared retry boundary."""

    return retry_youtube_api(context, sleep=sleep, jitter=jitter, on_attempt=on_attempt)(request.execute)()
