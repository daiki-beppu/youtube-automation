"""Browser and HTTP integration boundary."""

from collections.abc import Callable
from urllib import error, request
from urllib.parse import urlparse as _urlparse


class RedirectRejectedError(Exception):
    """Raised when an HTTP fetch attempts to follow a redirect."""


def parse_url(value: str):
    return _urlparse(value)


def fetch_html(url: str, *, timeout: float, validator: Callable[[str], None] | None = None) -> bytes:
    """Fetch HTML without following redirects; URL policy stays at the caller boundary."""

    class _NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise RedirectRejectedError

    if validator is not None:
        validator(url)
    try:
        req = request.Request(url, method="GET")
        opener = request.build_opener(_NoRedirect())
        with opener.open(req, timeout=timeout) as response:
            return response.read()
    except RedirectRejectedError:
        raise
    except (error.URLError, TimeoutError):
        raise
