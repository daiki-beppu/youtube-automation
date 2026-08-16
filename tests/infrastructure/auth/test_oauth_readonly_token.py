"""OAuth token の scope 分離（#1699）のユニットテスト。

read-only skill が write scope を共用しないための 3 点を検証する:

1. ``READONLY_SCOPES`` に write scope（youtube / youtube.force-ssl）が含まれない
2. ``token.readonly.json`` の解決（channel 側 → main worktree 側 → 未発行 None）
3. ``YouTubeClients`` が full/read-only handler を分離して扱う
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import google.auth.exceptions
import pytest

from youtube_automation.core.errors import AuthError
from youtube_automation.infrastructure.auth.youtube import YouTubeOAuthHandler
from youtube_automation.infrastructure.google.youtube import YouTubeClients

_WRITE_SCOPES = (
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
)


def _make_worktree_pair(tmp_path: Path) -> tuple[Path, Path]:
    """main 作業ツリーと linked worktree の最小構造を作る（test_oauth_worktree_fallback と同型）。"""
    main_root = tmp_path / "main"
    worktree = tmp_path / "wt"

    gitdir = main_root / ".git" / "worktrees" / "wt"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")

    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    return main_root, worktree


def _create_readonly_handler(tmp_path: Path, monkeypatch, *, interactive: bool):
    channel = tmp_path / "channel"
    (channel / "auth").mkdir(parents=True)
    monkeypatch.delenv("CLIENT_SECRETS_DIR", raising=False)
    monkeypatch.setenv("CHANNEL_DIR", str(channel))
    handler = YouTubeOAuthHandler.create_readonly(interactive=interactive)
    handler._validate_client_secrets = MagicMock()
    return handler


class TestReadonlyScopes:
    def test_readonly_scopes_contain_no_write_scope(self):
        """READONLY_SCOPES に write scope が混入しない（#1699 の核心）"""
        for write_scope in _WRITE_SCOPES:
            assert write_scope not in YouTubeOAuthHandler.READONLY_SCOPES

    def test_readonly_scopes_are_all_readonly_suffixed(self):
        """全 scope が .readonly サフィックス（将来の追加でも機械的に担保）"""
        assert YouTubeOAuthHandler.READONLY_SCOPES
        for scope in YouTubeOAuthHandler.READONLY_SCOPES:
            assert scope.endswith(".readonly"), scope

    def test_full_scopes_keep_write_scopes(self):
        """既存の SCOPES（token.json）は従来どおり write scope を保持（要件 2 の regression guard）"""
        for write_scope in _WRITE_SCOPES:
            assert write_scope in YouTubeOAuthHandler.SCOPES


class TestReadonlyTokenPath:
    def test_unissued_returns_none(self, tmp_path, monkeypatch):
        channel = tmp_path / "channel"
        channel.mkdir()
        monkeypatch.setenv("CHANNEL_DIR", str(channel))

        assert YouTubeOAuthHandler.readonly_token_path() is None

    def test_channel_local_token_wins(self, tmp_path, monkeypatch):
        channel = tmp_path / "channel"
        (channel / "auth").mkdir(parents=True)
        token = channel / "auth" / "token.readonly.json"
        token.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("CHANNEL_DIR", str(channel))

        assert YouTubeOAuthHandler.readonly_token_path() == token

    def test_worktree_falls_back_to_main_auth(self, tmp_path, monkeypatch):
        """worktree にローカル token が無ければ main 側 auth/ を探す（#1721 と同型）"""
        main_root, worktree = _make_worktree_pair(tmp_path)
        token = main_root / "auth" / "token.readonly.json"
        token.parent.mkdir(parents=True)
        token.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("CHANNEL_DIR", str(worktree))

        assert YouTubeOAuthHandler.readonly_token_path() == token.resolve()


class TestCreateReadonly:
    def test_issued_token_selected_with_readonly_scopes(self, tmp_path, monkeypatch):
        channel = tmp_path / "channel"
        (channel / "auth").mkdir(parents=True)
        token = channel / "auth" / "token.readonly.json"
        token.write_text("{}", encoding="utf-8")
        monkeypatch.delenv("CLIENT_SECRETS_DIR", raising=False)
        monkeypatch.setenv("CHANNEL_DIR", str(channel))

        handler = YouTubeOAuthHandler.create_readonly()
        assert handler.token_file == token
        assert handler._scopes == YouTubeOAuthHandler.READONLY_SCOPES

    def test_unissued_defaults_to_channel_auth(self, tmp_path, monkeypatch):
        """未発行なら channel/auth/token.readonly.json を発行先にする"""
        channel = tmp_path / "channel"
        (channel / "auth").mkdir(parents=True)
        monkeypatch.delenv("CLIENT_SECRETS_DIR", raising=False)
        monkeypatch.setenv("CHANNEL_DIR", str(channel))

        handler = YouTubeOAuthHandler.create_readonly()
        assert handler.token_file == channel / "auth" / "token.readonly.json"

    def test_unissued_in_worktree_targets_main_auth(self, tmp_path, monkeypatch):
        """worktree で未発行なら main 側 auth/ を発行先にする（分岐防止・#1721 と同型）"""
        main_root, worktree = _make_worktree_pair(tmp_path)
        (main_root / "auth").mkdir(parents=True)
        monkeypatch.delenv("CLIENT_SECRETS_DIR", raising=False)
        monkeypatch.setenv("CHANNEL_DIR", str(worktree))

        handler = YouTubeOAuthHandler.create_readonly()
        assert handler.token_file == main_root.resolve() / "auth" / "token.readonly.json"


class TestReadonlyInteractivePolicy:
    def test_noninteractive_missing_token_fails_with_issue_command_before_browser(self, tmp_path, monkeypatch):
        handler = _create_readonly_handler(tmp_path, monkeypatch, interactive=False)
        browser_flow = MagicMock()
        monkeypatch.setattr(
            "youtube_automation.infrastructure.auth.youtube.InstalledAppFlow.from_client_secrets_file",
            browser_flow,
        )

        with pytest.raises(AuthError, match=r"uv run yt-oauth --readonly"):
            handler.authenticate()

        browser_flow.assert_not_called()

    def test_noninteractive_invalid_token_fails_before_browser(self, tmp_path, monkeypatch):
        handler = _create_readonly_handler(tmp_path, monkeypatch, interactive=False)
        handler.token_file.write_text("{}", encoding="utf-8")
        browser_flow = MagicMock()
        monkeypatch.setattr(
            "youtube_automation.infrastructure.auth.youtube.Credentials.from_authorized_user_file",
            MagicMock(side_effect=ValueError("invalid token")),
        )
        monkeypatch.setattr(
            "youtube_automation.infrastructure.auth.youtube.InstalledAppFlow.from_client_secrets_file",
            browser_flow,
        )

        with pytest.raises(AuthError, match=r"uv run yt-oauth --readonly"):
            handler.authenticate()

        browser_flow.assert_not_called()

    def test_noninteractive_refresh_failure_fails_before_browser(self, tmp_path, monkeypatch):
        handler = _create_readonly_handler(tmp_path, monkeypatch, interactive=False)
        handler.token_file.write_text("{}", encoding="utf-8")
        credentials = MagicMock(expired=True, valid=False, refresh_token="refresh-token")
        credentials.refresh.side_effect = google.auth.exceptions.RefreshError("revoked")
        browser_flow = MagicMock()
        monkeypatch.setattr(
            "youtube_automation.infrastructure.auth.youtube.Credentials.from_authorized_user_file",
            MagicMock(return_value=credentials),
        )
        monkeypatch.setattr(
            "youtube_automation.infrastructure.auth.youtube.InstalledAppFlow.from_client_secrets_file",
            browser_flow,
        )

        with pytest.raises(AuthError, match=r"uv run yt-oauth --readonly"):
            handler.authenticate()

        browser_flow.assert_not_called()

    def test_noninteractive_refresh_transport_failure_fails_before_browser(self, tmp_path, monkeypatch):
        handler = _create_readonly_handler(tmp_path, monkeypatch, interactive=False)
        handler.token_file.write_text("{}", encoding="utf-8")
        credentials = MagicMock(expired=True, valid=False, refresh_token="refresh-token")
        credentials.refresh.side_effect = google.auth.exceptions.TransportError("network unavailable")
        browser_flow = MagicMock()
        monkeypatch.setattr(
            "youtube_automation.infrastructure.auth.youtube.Credentials.from_authorized_user_file",
            MagicMock(return_value=credentials),
        )
        monkeypatch.setattr(
            "youtube_automation.infrastructure.auth.youtube.InstalledAppFlow.from_client_secrets_file",
            browser_flow,
        )

        with pytest.raises(AuthError, match=r"uv run yt-oauth --readonly"):
            handler.authenticate()

        browser_flow.assert_not_called()

    def test_noninteractive_valid_token_is_reused(self, tmp_path, monkeypatch):
        handler = _create_readonly_handler(tmp_path, monkeypatch, interactive=False)
        handler.token_file.write_text("{}", encoding="utf-8")
        credentials = MagicMock(expired=False, valid=True)
        monkeypatch.setattr(
            "youtube_automation.infrastructure.auth.youtube.Credentials.from_authorized_user_file",
            MagicMock(return_value=credentials),
        )

        assert handler.authenticate() is credentials
        handler._validate_client_secrets.assert_not_called()

    def test_noninteractive_refreshable_token_is_refreshed(self, tmp_path, monkeypatch):
        handler = _create_readonly_handler(tmp_path, monkeypatch, interactive=False)
        handler.token_file.write_text("{}", encoding="utf-8")
        credentials = MagicMock(expired=True, valid=False, refresh_token="refresh-token")

        def mark_valid(_request):
            credentials.expired = False
            credentials.valid = True

        credentials.refresh.side_effect = mark_valid
        monkeypatch.setattr(
            "youtube_automation.infrastructure.auth.youtube.Credentials.from_authorized_user_file",
            MagicMock(return_value=credentials),
        )
        handler._save_credentials = MagicMock()

        assert handler.authenticate() is credentials
        credentials.refresh.assert_called_once()
        handler._save_credentials.assert_called_once_with()

    def test_default_policy_keeps_interactive_browser_flow(self, tmp_path, monkeypatch):
        handler = _create_readonly_handler(tmp_path, monkeypatch, interactive=True)
        credentials = MagicMock(expired=False, valid=True)
        flow = MagicMock()
        flow.run_local_server.return_value = credentials
        browser_flow = MagicMock(return_value=flow)
        monkeypatch.setattr(
            "youtube_automation.infrastructure.auth.youtube.InstalledAppFlow.from_client_secrets_file",
            browser_flow,
        )
        handler._save_credentials = MagicMock()

        assert handler.authenticate() is credentials
        browser_flow.assert_called_once()
        flow.run_local_server.assert_called_once()


class TestYouTubeClientsReadonly:
    def test_youtube_and_youtube_readonly_use_separate_handlers(self):
        full_handler = MagicMock(name="full_handler")
        readonly_handler = MagicMock(name="readonly_handler")
        full_handler.get_youtube_service.return_value = "full"
        readonly_handler.get_youtube_service.return_value = "readonly"
        clients = YouTubeClients(full_handler=full_handler, readonly_handler=readonly_handler)

        assert clients.youtube == "full"
        assert clients.youtube_readonly == "readonly"
        full_handler.get_youtube_service.assert_called_once_with()
        readonly_handler.get_youtube_service.assert_called_once_with()

    def test_readonly_falls_back_to_full_handler_when_not_injected(self):
        full_handler = MagicMock(name="full_handler")
        full_handler.get_youtube_service.return_value = "full"
        clients = YouTubeClients(full_handler=full_handler)

        assert clients.youtube_readonly == "full"

    def test_reset_clears_readonly_service_cache(self):
        handler = MagicMock()
        handler.get_youtube_service.side_effect = ["first", "second"]
        clients = YouTubeClients(full_handler=handler)

        assert clients.youtube_readonly == "first"
        clients.reset()
        assert clients.youtube_readonly == "second"


class TestMainReadonlyFlag:
    def test_refresh_only_uses_noninteractive_handler_without_connection_test(self):
        from youtube_automation.commands.system import oauth as oauth_cli

        mock_cls = MagicMock()
        with patch.object(oauth_cli, "YouTubeOAuthHandler", mock_cls):
            oauth_cli.main(["--refresh-only"])

        mock_cls.assert_called_once_with(interactive=False)
        mock_cls.return_value.refresh_existing_credentials.assert_called_once_with()
        mock_cls.return_value.authenticate.assert_not_called()
        mock_cls.return_value.test_connection.assert_not_called()

    def test_refresh_failure_redacts_secret_and_reports_interactive_reauthentication(self, caplog):
        from youtube_automation.commands.system import oauth as oauth_cli

        leaked_refresh_token = "1//secret-refresh-token"
        mock_cls = MagicMock()
        mock_cls.return_value.refresh_existing_credentials.side_effect = AuthError(
            f"invalid_grant refresh_token={leaked_refresh_token}"
        )
        caplog.set_level("ERROR", logger=oauth_cli.__name__)

        with patch.object(oauth_cli, "YouTubeOAuthHandler", mock_cls), pytest.raises(SystemExit) as error:
            oauth_cli.main(["--refresh-only"])

        assert error.value.code == 1
        assert leaked_refresh_token not in caplog.text
        assert "uv run yt-oauth`" in caplog.text

    def test_readonly_flag_uses_create_readonly(self):
        from youtube_automation.commands.system import oauth as oauth_cli

        mock_cls = MagicMock()
        mock_cls.create_readonly.return_value.test_connection.return_value = True
        with patch.object(oauth_cli, "YouTubeOAuthHandler", mock_cls):
            oauth_cli.main(["--readonly"])

        mock_cls.create_readonly.assert_called_once_with()
        mock_cls.assert_not_called()

    def test_default_uses_full_handler(self):
        from youtube_automation.commands.system import oauth as oauth_cli

        mock_cls = MagicMock()
        mock_cls.return_value.test_connection.return_value = True
        with patch.object(oauth_cli, "YouTubeOAuthHandler", mock_cls):
            oauth_cli.main([])

        mock_cls.assert_called_once_with()
        mock_cls.create_readonly.assert_not_called()
