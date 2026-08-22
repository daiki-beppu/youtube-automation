"""OAuth の人間向け進捗が machine-readable stdout を汚染しないことを検証する。"""

from __future__ import annotations

from types import SimpleNamespace

from youtube_automation.infrastructure.auth import youtube


def test_authenticate_writes_progress_only_to_stderr(tmp_path, monkeypatch, capsys) -> None:
    token_file = tmp_path / "token.json"
    token_file.write_text("{}", encoding="utf-8")
    credentials = SimpleNamespace(valid=True, expired=False, refresh_token="refresh-token")
    handler = object.__new__(youtube.YouTubeOAuthHandler)
    handler.credentials = None
    handler.token_file = token_file
    handler._scopes = youtube.YouTubeOAuthHandler.READONLY_SCOPES
    handler._ephemeral_credentials = False
    monkeypatch.setattr(handler, "_load_secret_credentials", lambda: None)
    monkeypatch.setattr(
        youtube.Credentials,
        "from_authorized_user_file",
        lambda *_args, **_kwargs: credentials,
    )

    assert handler.authenticate() is credentials

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "OAuth 2.0 認証開始" in captured.err
    assert "既存トークン読み込み成功" in captured.err
