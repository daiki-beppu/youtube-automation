"""OAuth refresh closes its session without relying on request destruction."""

from unittest.mock import Mock

import google.auth.exceptions
import pytest
from requests import Session

from youtube_automation.infrastructure.auth import youtube


@pytest.mark.parametrize("fails", [False, True])
def test_refresh_closes_transport_even_when_request_remains_referenced(monkeypatch, fails):
    session = Session()
    close = Mock(wraps=session.close)
    monkeypatch.setattr(session, "close", close)
    monkeypatch.setattr(youtube, "Session", lambda: session)
    retained_requests = []

    def refresh(request):
        retained_requests.append(request)
        assert request.session is session
        close.assert_not_called()
        if fails:
            raise google.auth.exceptions.RefreshError("refresh rejected")

    credentials = Mock(refresh=refresh)
    if fails:
        with pytest.raises(google.auth.exceptions.RefreshError, match="refresh rejected"):
            youtube._refresh_credentials(credentials)
    else:
        youtube._refresh_credentials(credentials)
    close.assert_called_once_with()
    assert len(retained_requests) == 1
