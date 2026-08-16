"""Browser HTTP boundary の redirect / network failure 契約テスト。"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock
from urllib import error

import pytest

from youtube_automation.infrastructure import browser


def test_fetch_html_validates_url_and_returns_response_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    response = MagicMock()
    response.read.return_value = b"<html>ok</html>"
    opener = MagicMock()
    opener.open.return_value = nullcontext(response)
    build_opener = MagicMock(return_value=opener)
    validator = MagicMock()
    monkeypatch.setattr(browser.request, "build_opener", build_opener)

    result = browser.fetch_html("https://allowed.example/page", timeout=2.5, validator=validator)

    assert result == b"<html>ok</html>"
    validator.assert_called_once_with("https://allowed.example/page")
    request_arg = opener.open.call_args.args[0]
    assert request_arg.full_url == "https://allowed.example/page"
    assert request_arg.get_method() == "GET"
    assert opener.open.call_args.kwargs == {"timeout": 2.5}
    assert isinstance(build_opener.call_args.args[0], browser.request.HTTPRedirectHandler)


def test_fetch_html_rejects_redirect_without_opening_second_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def build_opener(handler):
        opener = MagicMock()
        opener.open.side_effect = lambda *_args, **_kwargs: handler.redirect_request(
            None, None, 302, "Found", {}, "https://rejected.example"
        )
        return opener

    monkeypatch.setattr(browser.request, "build_opener", build_opener)

    with pytest.raises(browser.RedirectRejectedError):
        browser.fetch_html("https://allowed.example", timeout=1)


@pytest.mark.parametrize(
    "failure",
    [
        error.URLError("network unavailable"),
        TimeoutError("request timed out"),
    ],
)
def test_fetch_html_propagates_network_failures(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    opener = MagicMock()
    opener.open.side_effect = failure
    monkeypatch.setattr(browser.request, "build_opener", lambda *_handlers: opener)

    with pytest.raises(type(failure), match=str(failure)):
        browser.fetch_html("https://allowed.example", timeout=1)


def test_open_local_file_uses_absolute_file_uri(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "workflow status.html"
    opened = MagicMock(return_value=True)
    monkeypatch.setattr(browser.webbrowser, "open", opened)

    assert browser.open_local_file(target) is True
    opened.assert_called_once_with(target.resolve().as_uri())


def test_open_local_file_reports_browser_rejection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(browser.webbrowser, "open", lambda _uri: False)

    assert browser.open_local_file(tmp_path / "workflow-status.html") is False
