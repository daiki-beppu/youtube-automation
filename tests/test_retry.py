import json
from unittest.mock import Mock

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response, ServerNotFoundError

from youtube_automation.utils.exceptions import YouTubeAPIError
from youtube_automation.utils.retry import retry_youtube_api


def _http_error(status: int, reason: str) -> HttpError:
    content = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()
    return HttpError(Response({"status": str(status)}), content)


def test_retries_503_twice_then_returns_success() -> None:
    operation = Mock(side_effect=[_http_error(503, "backendError"), _http_error(503, "backendError"), "ok"])
    sleep = Mock()
    jitter = Mock(side_effect=[1.5, 3.0])

    result = retry_youtube_api("fetch", sleep=sleep, jitter=jitter)(operation)()

    assert result == "ok"
    assert operation.call_count == 3
    assert [call.args for call in jitter.call_args_list] == [(1, 2), (2, 4)]
    assert [call.args for call in sleep.call_args_list] == [(1.5,), (3.0,)]


def test_429_exhaustion_raises_domain_error() -> None:
    operation = Mock(side_effect=_http_error(429, "rateLimitExceeded"))

    with pytest.raises(YouTubeAPIError) as raised:
        retry_youtube_api("fetch", sleep=Mock(), jitter=lambda low, high: low)(operation)()

    assert operation.call_count == 3
    assert raised.value.status_code == 429
    assert raised.value.reason == "rateLimitExceeded"
    assert isinstance(raised.value.__cause__, HttpError)


def test_non_quota_403_fails_without_retry() -> None:
    operation = Mock(side_effect=_http_error(403, "commentsDisabled"))
    sleep = Mock()

    with pytest.raises(YouTubeAPIError) as raised:
        retry_youtube_api("fetch", sleep=sleep)(operation)()

    assert operation.call_count == 1
    assert sleep.call_count == 0
    assert raised.value.status_code == 403
    assert raised.value.reason == "commentsDisabled"


def test_quota_403_is_retried() -> None:
    operation = Mock(side_effect=[_http_error(403, "quotaExceeded"), "ok"])

    assert retry_youtube_api("fetch", sleep=Mock(), jitter=lambda low, high: low)(operation)() == "ok"
    assert operation.call_count == 2


def test_network_error_is_retried_and_exhaustion_is_domain_error() -> None:
    operation = Mock(side_effect=ServerNotFoundError("youtube.googleapis.com"))

    with pytest.raises(YouTubeAPIError) as raised:
        retry_youtube_api("fetch", sleep=Mock(), jitter=lambda low, high: low)(operation)()

    assert operation.call_count == 3
    assert isinstance(raised.value.__cause__, ServerNotFoundError)
