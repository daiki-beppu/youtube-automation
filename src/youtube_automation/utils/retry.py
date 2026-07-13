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
_QUOTA_REASONS = {
    "dailyLimitExceeded",
    "quotaExceeded",
    "rateLimitExceeded",
    "userRateLimitExceeded",
}


def _is_retryable(error: HttpError) -> bool:
    converted = YouTubeAPIError.from_http_error(error, "YouTube API request failed")
    status = converted.status_code
    return (
        status == 429
        or (status is not None and 500 <= status < 600)
        or (status == 403 and converted.reason in _QUOTA_REASONS)
    )


def retry_youtube_api(
    context: str,
    *,
    sleep: Callable[[float], None] | None = None,
    jitter: Callable[[float, float], float] | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Retry transient Google API failures and expose failures as domain errors."""
    sleep = sleep or time.sleep
    jitter = jitter or random.uniform

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

                delay = 2**attempt
                sleep(jitter(delay, delay * 2))

            raise AssertionError("retry loop exited unexpectedly")

        return wrapped

    return decorate


def execute_with_retry(request: ExecutableRequest[T], context: str) -> T:
    """Execute one Google API request through the shared retry boundary."""

    return retry_youtube_api(context)(request.execute)()
