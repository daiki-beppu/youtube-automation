from pathlib import Path
from unittest.mock import MagicMock

from google.auth.exceptions import RefreshError, TransportError

from youtube_automation.infrastructure.auth import tokens
from youtube_automation.infrastructure.auth import youtube as youtube_auth


def test_expired_credentials_are_refreshed_and_atomically_persisted(monkeypatch, tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text('{"token": "stale"}', encoding="utf-8")
    credentials = MagicMock(expired=True, refresh_token="refresh-token", valid=True)
    credentials.to_json.return_value = '{"token": "refreshed"}'
    monkeypatch.setattr(tokens, "load_credentials", lambda _path: credentials)

    state = tokens.load_refreshable_credentials(token_path)

    assert state.credentials is credentials
    assert state.refreshed is True
    assert state.error is None
    credentials.refresh.assert_called_once()
    assert token_path.read_text(encoding="utf-8") == '{"token": "refreshed"}'
    assert token_path.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.glob(f".{token_path.name}.*")) == []


def test_refresh_error_requires_reauthentication(monkeypatch, tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    credentials = MagicMock(expired=True, refresh_token="refresh-token", valid=False)
    credentials.refresh.side_effect = RefreshError("invalid_grant")
    monkeypatch.setattr(tokens, "load_credentials", lambda _path: credentials)

    state = tokens.load_refreshable_credentials(token_path)

    assert state.credentials is None
    assert state.error == "OAuth トークンの更新に失敗しました。更新用トークンが失効しています"
    assert state.reauthentication_required is True


def test_transport_error_does_not_require_reauthentication(monkeypatch, tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    credentials = MagicMock(expired=True, refresh_token="refresh-token", valid=False)
    credentials.refresh.side_effect = TransportError("offline")
    monkeypatch.setattr(tokens, "load_credentials", lambda _path: credentials)

    state = tokens.load_refreshable_credentials(token_path)

    assert state.credentials is None
    assert state.error == "OAuth トークン更新時の通信に失敗しました: offline"
    assert state.reauthentication_required is False


def test_atomic_save_failure_preserves_existing_token(monkeypatch, tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text('{"token": "original"}', encoding="utf-8")
    credentials = MagicMock()
    credentials.to_json.return_value = '{"token": "replacement"}'
    monkeypatch.setattr(tokens.os, "replace", MagicMock(side_effect=OSError("replace failed")))

    try:
        tokens.save_credentials(token_path, credentials)
    except OSError as error:
        assert str(error) == "replace failed"
    else:
        raise AssertionError("save_credentials must propagate atomic replacement failures")

    assert token_path.read_text(encoding="utf-8") == '{"token": "original"}'
    assert list(tmp_path.glob(f".{token_path.name}.*")) == []


def test_upload_required_scopes_are_owned_by_auth_boundary() -> None:
    assert youtube_auth.UPLOAD_REQUIRED_SCOPES == (
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.force-ssl",
    )


def test_build_youtube_service_uses_authenticated_credentials(monkeypatch) -> None:
    credentials = MagicMock()
    service = MagicMock()
    build = MagicMock(return_value=service)
    monkeypatch.setattr(youtube_auth, "build", build)

    assert youtube_auth.build_youtube_service(credentials) is service
    build.assert_called_once_with("youtube", "v3", credentials=credentials)
