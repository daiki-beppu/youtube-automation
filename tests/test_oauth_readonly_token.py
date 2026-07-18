"""OAuth token の scope 分離（#1699）のユニットテスト。

read-only skill が write scope を共用しないための 3 点を検証する:

1. ``READONLY_SCOPES`` に write scope（youtube / youtube.force-ssl）が含まれない
2. ``token.readonly.json`` の解決（channel 側 → main worktree 側 → 未発行 None）
3. ``ServiceRegistry`` の read 系が readonly token を優先し、未発行時は
   warning 付きで ``token.json`` へフォールバックする（サイレント失敗しない）
"""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler
from youtube_automation.utils.youtube_service import ServiceRegistry

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


class TestServiceRegistryReadonly:
    def test_unissued_falls_back_to_full_handler_with_warning(self, caplog):
        """未発行時は token.json ハンドラーへフォールバックし、発行手順を warning 案内する（要件 3）"""
        registry = ServiceRegistry()
        full_handler = MagicMock(name="full_handler")
        registry._get_handler = lambda: full_handler

        with (
            patch.object(YouTubeOAuthHandler, "readonly_token_path", return_value=None),
            caplog.at_level(logging.WARNING, logger="youtube_automation.utils.youtube_service"),
        ):
            resolved = registry._get_readonly_handler()

        assert resolved is full_handler
        assert "token.readonly.json" in caplog.text
        assert "yt-oauth --readonly" in caplog.text

    def test_issued_uses_readonly_handler(self, tmp_path, caplog):
        """発行済みなら readonly ハンドラーを使い、warning を出さない"""
        registry = ServiceRegistry()
        readonly_handler = MagicMock(name="readonly_handler")

        with (
            patch.object(
                YouTubeOAuthHandler,
                "readonly_token_path",
                return_value=tmp_path / "token.readonly.json",
            ),
            patch.object(YouTubeOAuthHandler, "create_readonly", return_value=readonly_handler),
            caplog.at_level(logging.WARNING, logger="youtube_automation.utils.youtube_service"),
        ):
            resolved = registry._get_readonly_handler()

        assert resolved is readonly_handler
        assert caplog.text == ""

    def test_injected_handler_is_shared_for_read_paths(self):
        """コンストラクタ注入時（テスト・DI）は read 系も同じハンドラーを共用する"""
        injected = MagicMock(name="injected")
        registry = ServiceRegistry(handler=injected)

        assert registry._get_readonly_handler() is injected

    def test_youtube_and_youtube_readonly_are_separate_caches(self):
        """全 scope の youtube と read-only の youtube_readonly は別サービスとしてキャッシュされる"""
        registry = ServiceRegistry()
        full_handler = MagicMock(name="full_handler")
        readonly_handler = MagicMock(name="readonly_handler")
        registry._get_handler = lambda: full_handler
        registry._readonly_handler = readonly_handler

        assert registry.youtube is full_handler.get_youtube_service.return_value
        assert registry.youtube_readonly is readonly_handler.get_youtube_service.return_value
        assert registry.youtube is not registry.youtube_readonly

    def test_analytics_uses_readonly_credentials(self):
        """analytics は readonly ハンドラーの credentials で build される"""
        registry = ServiceRegistry()
        readonly_handler = MagicMock(name="readonly_handler")
        registry._readonly_handler = readonly_handler

        with patch("youtube_automation.utils.youtube_service.build") as mock_build:
            _ = registry.analytics

        mock_build.assert_called_once_with(
            "youtubeAnalytics", "v2", credentials=readonly_handler.authenticate.return_value
        )

    def test_reset_clears_readonly_state(self):
        registry = ServiceRegistry()
        registry._readonly_handler = MagicMock()
        registry._youtube_readonly_service = MagicMock()

        registry.reset()

        assert registry._readonly_handler is None
        assert registry._youtube_readonly_service is None


class TestMainReadonlyFlag:
    def test_readonly_flag_uses_create_readonly(self):
        from youtube_automation.auth import oauth_handler

        mock_cls = MagicMock()
        mock_cls.create_readonly.return_value.test_connection.return_value = True
        with patch.object(oauth_handler, "YouTubeOAuthHandler", mock_cls):
            oauth_handler.main(["--readonly"])

        mock_cls.create_readonly.assert_called_once_with()
        mock_cls.assert_not_called()

    def test_default_uses_full_handler(self):
        from youtube_automation.auth import oauth_handler

        mock_cls = MagicMock()
        mock_cls.return_value.test_connection.return_value = True
        with patch.object(oauth_handler, "YouTubeOAuthHandler", mock_cls):
            oauth_handler.main([])

        mock_cls.assert_called_once_with()
        mock_cls.create_readonly.assert_not_called()
