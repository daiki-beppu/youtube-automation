"""Single-attempt request accounting and exception boundary contracts."""

from unittest.mock import Mock

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from youtube_automation.core.errors import YouTubeAPIError
from youtube_automation.infrastructure.google.youtube import execute_metered_request


def _http_error():
    return HttpError(Response({"status": 503}), b'{"error":{"message":"unavailable"}}')


@pytest.mark.parametrize("context", [None, "", "update metadata"])
def test_success_preserves_response_and_accounts_after_execute(context):
    response = {"id": "video"}
    events = []
    request = Mock()
    request.execute.side_effect = lambda: events.append("execute") or response
    result = execute_metered_request(request, error_context=context, on_finish=lambda: events.append("account"))
    assert result is response
    assert events == ["execute", "account"]
    request.execute.assert_called_once_with()


@pytest.mark.parametrize("context", [None, "", "update metadata"])
@pytest.mark.parametrize("http_failure", [False, True])
def test_failure_accounts_once_without_retry_and_preserves_error_policy(context, http_failure):
    failure = _http_error() if http_failure else OSError("connection failed")
    request = Mock()
    request.execute.side_effect = failure
    account = Mock()
    converted = http_failure and context is not None
    expected_type = YouTubeAPIError if converted else type(failure)
    with pytest.raises(expected_type) as caught:
        execute_metered_request(request, error_context=context, on_finish=account)
    request.execute.assert_called_once_with()
    account.assert_called_once_with()
    if converted:
        assert caught.value.__cause__ is failure
        assert caught.value.status_code == 503
        assert str(caught.value) == str(YouTubeAPIError.from_http_error(failure, context))
    else:
        assert caught.value is failure


@pytest.mark.parametrize("failure", [None, OSError("connection failed")])
def test_accounting_failure_is_propagated_without_reexecuting_request(failure):
    request = Mock()
    request.execute.side_effect = failure
    accounting_error = OSError("quota log unavailable")
    account = Mock(side_effect=accounting_error)
    with pytest.raises(OSError) as caught:
        execute_metered_request(request, on_finish=account)
    assert caught.value is accounting_error
    assert caught.value.__context__ is failure
    request.execute.assert_called_once_with()
    account.assert_called_once_with()
