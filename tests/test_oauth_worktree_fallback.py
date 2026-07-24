"""git worktree 上での auth/ フォールバック解決のユニットテスト（#1721）

worktree 構造（`.git` pointer ファイル + main 側 `.git/worktrees/<name>/commondir`）を
tmp_path 上に模して、client_secrets 候補列・token パス解決・エラーメッセージを検証する。
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from youtube_automation.infrastructure.auth.youtube import (
    YouTubeOAuthHandler,
    client_secrets_file_candidates,
    resolve_client_secrets_path,
)
from youtube_automation.utils.worktree import main_worktree_root

_CLIENT_SECRETS = {
    "installed": {
        "client_id": "dummy-id",
        "client_secret": "dummy-secret",
        "redirect_uris": ["http://localhost"],
    }
}


def _make_worktree_pair(tmp_path: Path) -> tuple[Path, Path]:
    """main 作業ツリーと linked worktree の最小構造を作る。

    Returns:
        (main_root, worktree_root)
    """
    main_root = tmp_path / "main"
    worktree = tmp_path / "wt"

    gitdir = main_root / ".git" / "worktrees" / "wt"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")

    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    return main_root, worktree


@pytest.fixture
def worktree_pair(tmp_path, monkeypatch):
    """worktree 構造を作り、CHANNEL_DIR を worktree に向ける。"""
    main_root, worktree = _make_worktree_pair(tmp_path)
    monkeypatch.delenv("CLIENT_SECRETS_DIR", raising=False)
    monkeypatch.setenv("CHANNEL_DIR", str(worktree))
    return main_root, worktree


class TestMainWorktreeRoot:
    def test_worktree_resolves_main_root(self, tmp_path):
        main_root, worktree = _make_worktree_pair(tmp_path)
        assert main_worktree_root(worktree) == main_root.resolve()

    def test_subdir_of_worktree_resolves_main_root(self, tmp_path):
        main_root, worktree = _make_worktree_pair(tmp_path)
        subdir = worktree / "collections" / "planning"
        subdir.mkdir(parents=True)
        assert main_worktree_root(subdir) == main_root.resolve()

    def test_main_worktree_returns_none(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        assert main_worktree_root(repo) is None

    def test_non_git_dir_returns_none(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert main_worktree_root(plain) is None

    def test_submodule_gitfile_returns_none(self, tmp_path):
        # submodule の .git ファイルは modules/ を指し commondir を持たない
        superproject = tmp_path / "super"
        module_gitdir = superproject / ".git" / "modules" / "sub"
        module_gitdir.mkdir(parents=True)
        sub = superproject / "sub"
        sub.mkdir()
        (sub / ".git").write_text(f"gitdir: {module_gitdir}\n", encoding="utf-8")
        assert main_worktree_root(sub) is None

    def test_broken_gitfile_returns_none(self, tmp_path):
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / ".git").write_text("not a gitdir pointer\n", encoding="utf-8")
        assert main_worktree_root(broken) is None


class TestClientSecretsCandidates:
    def test_workspace_root_auth_is_fallback_after_channel_candidates(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLIENT_SECRETS_DIR", raising=False)
        workspace = tmp_path / "workspace"
        channel = workspace / "channels" / "alpha"
        (channel / "config" / "channel").mkdir(parents=True)

        assert client_secrets_file_candidates(channel) == [
            channel / "auth" / "client_secrets.json",
            channel / "automation" / "auth" / "client_secrets.json",
            workspace / "auth" / "client_secrets.json",
        ]

    def test_resolve_prefers_channel_file_over_workspace_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLIENT_SECRETS_DIR", raising=False)
        workspace = tmp_path / "workspace"
        channel = workspace / "channels" / "alpha"
        (channel / "config" / "channel").mkdir(parents=True)
        for root in (workspace, channel):
            (root / "auth").mkdir(parents=True, exist_ok=True)
            (root / "auth" / "client_secrets.json").write_text(json.dumps(_CLIENT_SECRETS), encoding="utf-8")

        assert resolve_client_secrets_path(channel) == channel / "auth" / "client_secrets.json"

    def test_resolve_falls_back_to_workspace_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLIENT_SECRETS_DIR", raising=False)
        workspace = tmp_path / "workspace"
        channel = workspace / "channels" / "alpha"
        (channel / "config" / "channel").mkdir(parents=True)
        (workspace / "auth").mkdir()
        (workspace / "auth" / "client_secrets.json").write_text(json.dumps(_CLIENT_SECRETS), encoding="utf-8")

        assert resolve_client_secrets_path(channel) == workspace / "auth" / "client_secrets.json"

    def test_nested_standalone_repo_does_not_use_workspace_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLIENT_SECRETS_DIR", raising=False)
        workspace = tmp_path / "workspace"
        workspace_channel = workspace / "channels" / "alpha"
        (workspace_channel / "config" / "channel").mkdir(parents=True)
        standalone = workspace / "standalone"
        standalone.mkdir()

        assert client_secrets_file_candidates(standalone) == [
            standalone / "auth" / "client_secrets.json",
            standalone / "automation" / "auth" / "client_secrets.json",
        ]

    def test_worktree_appends_main_auth_fallback_last(self, worktree_pair):
        main_root, worktree = worktree_pair
        candidates = client_secrets_file_candidates(worktree)
        assert candidates[:2] == [
            worktree / "auth" / "client_secrets.json",
            worktree / "automation" / "auth" / "client_secrets.json",
        ]
        assert candidates[-1] == main_root.resolve() / "auth" / "client_secrets.json"

    def test_client_secrets_dir_env_takes_precedence(self, worktree_pair, monkeypatch, tmp_path):
        _, worktree = worktree_pair
        secrets_dir = tmp_path / "explicit"
        monkeypatch.setenv("CLIENT_SECRETS_DIR", str(secrets_dir))
        assert client_secrets_file_candidates(worktree) == [secrets_dir / "client_secrets.json"]

    def test_non_worktree_candidates_unchanged(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLIENT_SECRETS_DIR", raising=False)
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        assert client_secrets_file_candidates(repo) == [
            repo / "auth" / "client_secrets.json",
            repo / "automation" / "auth" / "client_secrets.json",
        ]

    def test_resolve_prefers_local_file_over_main_fallback(self, worktree_pair):
        main_root, worktree = worktree_pair
        for root in (main_root, worktree):
            (root / "auth").mkdir(parents=True, exist_ok=True)
            (root / "auth" / "client_secrets.json").write_text(json.dumps(_CLIENT_SECRETS), encoding="utf-8")
        assert resolve_client_secrets_path(worktree) == worktree / "auth" / "client_secrets.json"

    def test_resolve_falls_back_to_main_file(self, worktree_pair):
        main_root, worktree = worktree_pair
        (main_root / "auth").mkdir(parents=True)
        (main_root / "auth" / "client_secrets.json").write_text(json.dumps(_CLIENT_SECRETS), encoding="utf-8")
        assert resolve_client_secrets_path(worktree) == main_root.resolve() / "auth" / "client_secrets.json"


class TestHandlerTokenResolution:
    def test_token_falls_back_to_main_auth(self, worktree_pair):
        main_root, _ = worktree_pair
        (main_root / "auth").mkdir(parents=True)
        handler = YouTubeOAuthHandler()
        assert handler.token_file == main_root.resolve() / "auth" / "token.json"

    def test_local_token_wins_over_main(self, worktree_pair):
        main_root, worktree = worktree_pair
        for root in (main_root, worktree):
            (root / "auth").mkdir(parents=True, exist_ok=True)
            (root / "auth" / "token.json").write_text("{}", encoding="utf-8")
        handler = YouTubeOAuthHandler()
        assert handler.token_file == worktree / "auth" / "token.json"

    def test_explicit_auth_dir_is_not_redirected(self, worktree_pair, tmp_path):
        explicit = tmp_path / "explicit-auth"
        explicit.mkdir()
        handler = YouTubeOAuthHandler(auth_dir=explicit)
        assert handler.token_file == explicit / "token.json"

    def test_explicit_token_path_is_not_redirected(self, worktree_pair, tmp_path):
        token_path = tmp_path / "token_streaming.json"
        handler = YouTubeOAuthHandler(token_path=token_path)
        assert handler.token_file == token_path

    def test_non_worktree_token_resolution_unchanged(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLIENT_SECRETS_DIR", raising=False)
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        monkeypatch.setenv("CHANNEL_DIR", str(repo))
        handler = YouTubeOAuthHandler()
        assert handler.token_file == repo / "auth" / "token.json"

    def test_refresh_write_goes_to_main_token(self, worktree_pair):
        main_root, _ = worktree_pair
        (main_root / "auth").mkdir(parents=True)
        handler = YouTubeOAuthHandler()
        handler.credentials = SimpleNamespace(to_json=lambda: '{"token": "dummy"}')
        handler._save_credentials()
        saved = main_root.resolve() / "auth" / "token.json"
        assert saved.is_file()
        assert json.loads(saved.read_text(encoding="utf-8")) == {"token": "dummy"}


class TestMissingSecretsErrorMessage:
    def test_error_lists_main_side_path(self, worktree_pair):
        main_root, _ = worktree_pair
        handler = YouTubeOAuthHandler()
        with pytest.raises(FileNotFoundError) as excinfo:
            handler._validate_client_secrets()
        assert str(main_root.resolve() / "auth" / "client_secrets.json") in str(excinfo.value)
