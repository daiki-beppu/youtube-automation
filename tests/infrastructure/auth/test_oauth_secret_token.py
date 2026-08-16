from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from youtube_automation.core.errors import AuthError
from youtube_automation.infrastructure.auth import youtube


def _handler(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> youtube.YouTubeOAuthHandler:
    monkeypatch.setattr(youtube, "resolve_client_secrets_source", lambda _channel: (tmp_path / "missing.json", None))
    return youtube.YouTubeOAuthHandler(token_path=tmp_path / "missing-token.json", interactive=False)


def test_cloud_oauth_token_is_loaded_from_secret_without_file_write(monkeypatch, tmp_path: Path) -> None:
    token = {
        "token": "access-secret",
        "refresh_token": "refresh-secret",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "scopes": ["https://www.googleapis.com/auth/youtube"],
    }
    monkeypatch.setenv("YOUTUBE_OAUTH_TOKEN_JSON", json.dumps(token))
    credentials = MagicMock(valid=True, expired=False)
    loader = MagicMock(return_value=credentials)
    monkeypatch.setattr(youtube.Credentials, "from_authorized_user_info", loader)
    handler = _handler(monkeypatch, tmp_path)

    assert handler.authenticate() is credentials
    loader.assert_called_once_with(token, handler._scopes)
    assert not handler.token_file.exists()


def test_cloud_oauth_token_refresh_stays_ephemeral(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "YOUTUBE_OAUTH_TOKEN_JSON",
        json.dumps(
            {
                "refresh_token": "secret",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "client-id",
                "client_secret": "client-secret",
            }
        ),
    )
    credentials = MagicMock(valid=True, expired=True, refresh_token="secret")
    monkeypatch.setattr(youtube.Credentials, "from_authorized_user_info", lambda *_args: credentials)
    save = MagicMock()
    monkeypatch.setattr(youtube, "save_credentials", save)
    handler = _handler(monkeypatch, tmp_path)

    assert handler.authenticate() is credentials
    credentials.refresh.assert_called_once()
    save.assert_not_called()


@pytest.mark.parametrize("value", ["not-json", "[]", "{}"])
def test_invalid_cloud_oauth_token_fails_without_interactive_fallback(monkeypatch, tmp_path: Path, value: str) -> None:
    monkeypatch.setenv("YOUTUBE_OAUTH_TOKEN_JSON", value)
    handler = _handler(monkeypatch, tmp_path)

    with pytest.raises(AuthError, match="YOUTUBE_OAUTH_TOKEN_JSON"):
        handler.authenticate()
