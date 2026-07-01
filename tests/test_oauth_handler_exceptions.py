"""issue #171: ``YouTubeOAuthHandler`` の例外 narrow / ``_redact`` / logger 化テスト。

検証対象:

- ``utils.exceptions.AuthError`` の追加（R1）
- ``oauth_handler._redact()`` ヘルパー（R9-a / R9-b）
- L74 / L132 / L144 / L159 / L202 / L230 の ``except`` narrow（R2〜R8）
- ``print`` → ``logger`` 置換と ``_redact`` による path / token leak 防止

テスト方針（test-design.md §テスト方針 準拠）:

- 実装を通すことを基本とし、外部依存のみ ``monkeypatch`` で差し替える
- ``caplog`` で logger 経由のメッセージを検証する
- sentinel テストで narrow 効果（想定外例外を握りつぶさないこと）を保証する
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import google.auth.exceptions
import pytest
from googleapiclient.errors import HttpError

from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler, _redact
from youtube_automation.utils.exceptions import (
    AuthError,
    AutomationError,
    ConfigError,
    YouTubeAPIError,
)

# ---------------------------------------------------------------------------
# モジュール定数（leak sentinel 入力）
# ---------------------------------------------------------------------------

# 実 OAuth token 風の文字列。`_redact()` がこれを残すと CI ログにリークする。
_LEAKY_ACCESS_TOKEN = "ya29.A0AbCdEfGhIjKlMnOpQrStUvWxYz123456"
_LEAKY_REFRESH_TOKEN = "1//06AbCdEfGhIjKlMnOpQrStUvWxYz_payload"
_LEAKY_JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTYifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"

# 「絶対パスがログに出る」ケースを再現する canary。実機の token / client_secrets path
# の代わりに固定文字列を使うことでテストの再現性を担保する。
_LEAKY_TOKEN_PATH = "/Users/leak-canary/auth/token.json"
_LEAKY_CLIENT_SECRETS = "/Users/leak-canary/auth/client_secrets.json"

_LOGGER_NAME = "youtube_automation.auth.oauth_handler"


# ---------------------------------------------------------------------------
# テストヘルパー
# ---------------------------------------------------------------------------


def _make_handler(
    tmp_path: Path,
    *,
    token_path: Path | None = None,
    client_secrets_file: Path | None = None,
) -> YouTubeOAuthHandler:
    """OAuth フロー / client_secrets 検証をバイパスした handler を作る。

    既存 ``tests/test_oauth_save_credentials.py::_build_handler`` の踏襲だが、
    本テストでは ``_validate_client_secrets`` を no-op に差し替え、物理ファイルを
    用意せずに認証経路だけを単離して検証する。
    """
    if token_path is None:
        token_path = tmp_path / "token.json"
    handler = YouTubeOAuthHandler(token_path=token_path)
    if client_secrets_file is not None:
        handler.client_secrets_file = client_secrets_file
    handler._validate_client_secrets = lambda: None  # type: ignore[method-assign]
    return handler


def _make_http_error(status: int = 503, reason: str = "Service Unavailable") -> HttpError:
    """``HttpError`` を最小構成で組み立てる（``test_competitor_discovery.py`` 同様のパターン）。"""
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp=resp, content=b'{"error": {"message": "test"}}')


def _make_credentials(
    *,
    expired: bool = False,
    valid: bool = True,
    refresh_token: str | None = "rt-test",
    refresh_side_effect: object | None = None,
) -> MagicMock:
    """``Credentials`` の擬装。``expired`` / ``valid`` / ``refresh_token`` / ``refresh()`` を制御する。"""
    creds = MagicMock()
    creds.expired = expired
    creds.valid = valid
    creds.refresh_token = refresh_token
    creds.to_json.return_value = '{"token": "x"}'
    if refresh_side_effect is not None:
        creds.refresh.side_effect = refresh_side_effect
    return creds


# ===========================================================================
# 1. AuthError クラス（#1, #2）
# ===========================================================================


class TestAuthErrorClass:
    """``AuthError`` の最小 contract（R1）。"""

    def test_should_be_a_subclass_of_automation_error(self):
        """Given ``AuthError``
        When 継承関係を確認
        Then ``AutomationError`` のサブクラス。

        既存呼び出し元の ``except Exception`` / ``except AutomationError`` 互換性を担保する。
        """
        assert issubclass(AuthError, AutomationError)

    def test_should_preserve_message_via_str(self):
        """Given ``AuthError("msg")``
        When ``str()``
        Then 渡したメッセージがそのまま返る。
        """
        assert str(AuthError("認証失敗")) == "認証失敗"


# ===========================================================================
# 2. _redact() — token mask（#3〜#9）
# ===========================================================================


class TestRedactToken:
    """``_redact()`` の token 値マスク（R9-a）。"""

    def test_should_leave_clean_message_untouched(self):
        """Given token / path を含まない message
        When ``_redact``
        Then 返り値は入力と同一（誤マスク防止）。
        """
        message = "OAuth flow timed out"
        assert _redact(message) == message

    def test_should_mask_google_access_token(self):
        """Given ``ya29.*`` を含む message
        When ``_redact``
        Then 生 access token が出力に残らない。
        """
        message = f"refresh failed token={_LEAKY_ACCESS_TOKEN}"
        assert _LEAKY_ACCESS_TOKEN not in _redact(message)

    def test_should_mask_google_refresh_token(self):
        """Given ``1//*`` を含む message
        When ``_redact``
        Then 生 refresh token が出力に残らない。
        """
        message = f"got refresh: {_LEAKY_REFRESH_TOKEN}"
        assert _LEAKY_REFRESH_TOKEN not in _redact(message)

    def test_should_mask_jwt_shaped_token(self):
        """Given JWT 風 3 セグメント token
        When ``_redact``
        Then 出力に残らない。
        """
        message = f"id_token: {_LEAKY_JWT} expired"
        assert _LEAKY_JWT not in _redact(message)

    def test_should_mask_refresh_token_keyvalue(self):
        """Given ``refresh_token=...`` 形式の key=value
        When ``_redact``
        Then 値部分が残らない。
        """
        message = "POST refresh_token=secret-value-xyz HTTP/1.1"
        assert "secret-value-xyz" not in _redact(message)

    @pytest.mark.parametrize("key", ["access_token", "client_secret", "id_token"])
    def test_should_mask_sensitive_keyvalue_pairs(self, key: str):
        """Given ``access_token`` / ``client_secret`` / ``id_token`` の key=value
        When ``_redact``
        Then 値部分が残らない（複数 sensitive key の網羅）。
        """
        message = f"request body: {key}=top-secret-payload&grant_type=refresh"
        assert "top-secret-payload" not in _redact(message)

    def test_should_mask_multiple_tokens_in_single_message(self):
        """Given 複数 token が同一 message に出現
        When ``_redact``
        Then すべてマスクされる（取りこぼし検知）。
        """
        message = f"a={_LEAKY_ACCESS_TOKEN} r={_LEAKY_REFRESH_TOKEN}"
        result = _redact(message)
        assert _LEAKY_ACCESS_TOKEN not in result
        assert _LEAKY_REFRESH_TOKEN not in result


# ===========================================================================
# 3. _redact() — path mask（#10〜#15）
# ===========================================================================


class TestRedactPath:
    """``_redact()`` の path マスク（R9-b）。"""

    def test_should_mask_absolute_path_in_oserrno_format(self):
        """Given ``OSError`` の str（``: '<abs path>'`` 形式）
        When ``_redact``
        Then 絶対パスが残らない。

        ``Credentials.from_authorized_user_file`` の ``OSError`` は
        第 3 引数 filename を必ず ``str()`` 末尾に含む仕様（CPython 標準）。
        """
        message = f"[Errno 2] No such file or directory: '{_LEAKY_TOKEN_PATH}'"
        assert _LEAKY_TOKEN_PATH not in _redact(message)

    def test_should_mask_literal_path_arg(self):
        """Given path 文字列が message 中に literal で出現
        When ``_redact(message, Path(...))``
        Then 渡した ``Path`` のパス文字列が出力に残らない。
        """
        message = f"failed to open {_LEAKY_TOKEN_PATH}"
        assert _LEAKY_TOKEN_PATH not in _redact(message, Path(_LEAKY_TOKEN_PATH))

    def test_should_mask_literal_str_arg(self):
        """Given path 文字列が ``str`` で渡される
        When ``_redact(message, "...")``
        Then ``os.fspath`` 経路で literal マスクされる。
        """
        message = f"failed to open {_LEAKY_TOKEN_PATH}"
        assert _LEAKY_TOKEN_PATH not in _redact(message, _LEAKY_TOKEN_PATH)

    def test_should_mask_multiple_paths_via_varargs(self):
        """Given 2 つの path が ``*paths`` で渡される
        When ``_redact``
        Then 両方マスクされる（L230 の ``token_file`` + ``client_secrets_file`` 経路）。
        """
        message = f"open {_LEAKY_TOKEN_PATH} and {_LEAKY_CLIENT_SECRETS}"
        result = _redact(message, _LEAKY_TOKEN_PATH, _LEAKY_CLIENT_SECRETS)
        assert _LEAKY_TOKEN_PATH not in result
        assert _LEAKY_CLIENT_SECRETS not in result

    def test_should_be_no_op_when_paths_arg_is_empty_and_message_has_no_leak(self):
        """Given 安全な message かつ ``paths`` 空
        When ``_redact``
        Then 入力と同一。
        """
        message = "everything is fine"
        assert _redact(message) == message

    def test_should_mask_token_and_path_simultaneously(self):
        """Given token と OSErrno 形式 path が混在
        When ``_redact``
        Then 両方マスクされる（実シナリオ: ``OSError`` 経路で token ヒント混在）。
        """
        message = f"[Errno 13] Permission denied: '{_LEAKY_TOKEN_PATH}' refresh_token={_LEAKY_REFRESH_TOKEN}"
        result = _redact(message, _LEAKY_TOKEN_PATH)
        assert _LEAKY_TOKEN_PATH not in result
        assert _LEAKY_REFRESH_TOKEN not in result


# ===========================================================================
# 4. L74 — 1Password fallback（#16, #17）
# ===========================================================================


class TestClientSecretsFallback:
    """``__init__`` の 1Password fallback の except narrow（R2）。"""

    def _force_fallback_path(self, monkeypatch, tmp_path: Path) -> None:
        """``CLIENT_SECRETS_DIR`` を解除し、``channel_dir()`` を空 tmp_path に向ける。

        candidates 配下に client_secrets.json は存在しないため
        必ず 1Password fallback ブロックに到達する。
        """
        monkeypatch.delenv("CLIENT_SECRETS_DIR", raising=False)
        monkeypatch.setattr(
            "youtube_automation.utils.config.channel_dir",
            lambda: tmp_path,
        )

    def test_should_fallback_to_default_candidate_when_get_client_secrets_path_raises_config_error(
        self, tmp_path: Path, monkeypatch
    ):
        """Given 1Password 取得が ``ConfigError`` を raise
        When ``YouTubeOAuthHandler()``
        Then ``candidates[0]``（``<channel_dir>/auth/client_secrets.json``）にフォールバック。
        """
        self._force_fallback_path(monkeypatch, tmp_path)
        monkeypatch.setattr(
            "youtube_automation.utils.secrets.get_client_secrets_path",
            MagicMock(side_effect=ConfigError("op read failed")),
        )

        handler = YouTubeOAuthHandler()

        assert handler.client_secrets_file == tmp_path / "auth" / "client_secrets.json"

    def test_should_use_submodule_candidate_before_one_password_fallback(self, tmp_path: Path, monkeypatch):
        """Given submodule 互換 path に client_secrets.json がある
        When ``YouTubeOAuthHandler()``
        Then 1Password fallback を呼ばずにその path を使う。
        """
        self._force_fallback_path(monkeypatch, tmp_path)
        submodule_path = tmp_path / "automation" / "auth" / "client_secrets.json"
        submodule_path.parent.mkdir(parents=True)
        submodule_path.write_text('{"installed": {}}\n', encoding="utf-8")
        get_client_secrets_path = MagicMock(side_effect=ConfigError("should not be called"))
        monkeypatch.setattr(
            "youtube_automation.utils.secrets.get_client_secrets_path",
            get_client_secrets_path,
        )

        handler = YouTubeOAuthHandler()

        assert handler.client_secrets_file == submodule_path
        get_client_secrets_path.assert_not_called()

    def test_missing_client_secrets_error_follows_google_auth_platform_contract(self, tmp_path: Path, monkeypatch):
        """Missing secrets must point every direct OAuth entrypoint at the new Console UI."""
        self._force_fallback_path(monkeypatch, tmp_path)
        monkeypatch.setattr(
            "youtube_automation.utils.secrets.get_client_secrets_path",
            MagicMock(side_effect=ConfigError("op read failed")),
        )
        handler = YouTubeOAuthHandler()

        with pytest.raises(FileNotFoundError) as exc_info:
            handler._validate_client_secrets()

        message = str(exc_info.value)
        for expected in (
            "Google Auth Platform",
            "Audience > Test users",
            "403 access_denied",
            "Clients > Create client",
            "Desktop app",
            "Add secret",
            "auth/client_secrets.template.json",
        ):
            assert expected in message
        assert "OAuth 2.0 認証情報を作成" not in message
        assert "作成直後" not in message
        assert "JSON をダウンロード" not in message

    def test_should_not_swallow_non_config_error(self, tmp_path: Path, monkeypatch):
        """Given 1Password 取得が ``RuntimeError`` を raise（想定外）
        When ``YouTubeOAuthHandler()``
        Then 例外が伝播する（旧 ``except Exception`` の握りつぶし禁止）。

        ``except ConfigError`` への narrow の核心 sentinel。
        """
        self._force_fallback_path(monkeypatch, tmp_path)
        monkeypatch.setattr(
            "youtube_automation.utils.secrets.get_client_secrets_path",
            MagicMock(side_effect=RuntimeError("unexpected")),
        )

        with pytest.raises(RuntimeError):
            YouTubeOAuthHandler()


# ===========================================================================
# 5. L132 — 既存トークン読み込み（#18〜#21）
# ===========================================================================


class TestAuthenticateExistingTokenLoad:
    """L132: ``Credentials.from_authorized_user_file`` の except narrow（R3）。"""

    def _setup(self, tmp_path: Path, monkeypatch):
        """``token_file`` 存在 + 後続 new auth フロー mock 済みの handler を返す。"""
        token_path = tmp_path / "token.json"
        token_path.write_text("{}")  # exists() を真にするだけの dummy
        handler = _make_handler(tmp_path, token_path=token_path)

        new_creds = _make_credentials(valid=True, expired=False)
        flow = MagicMock()
        flow.run_local_server.return_value = new_creds
        monkeypatch.setattr(
            "youtube_automation.auth.oauth_handler.InstalledAppFlow.from_client_secrets_file",
            MagicMock(return_value=flow),
        )
        monkeypatch.setattr(handler, "_save_credentials", MagicMock())
        return handler, new_creds

    def test_should_set_credentials_none_and_continue_to_new_auth_flow_on_oserror(self, tmp_path: Path, monkeypatch):
        """Given ``from_authorized_user_file`` が ``OSError``
        When ``authenticate``
        Then ``credentials=None`` に落として新規認証へフォールスルー（recovery 維持）。
        """
        handler, new_creds = self._setup(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "youtube_automation.auth.oauth_handler.Credentials.from_authorized_user_file",
            MagicMock(side_effect=OSError(2, "No such file", str(handler.token_file))),
        )

        result = handler.authenticate()

        assert result is new_creds  # 新規認証フローが実行された

    def test_should_set_credentials_none_on_value_error(self, tmp_path: Path, monkeypatch):
        """Given ``from_authorized_user_file`` が ``ValueError``（JSON 不整合）
        When ``authenticate``
        Then 新規認証フローへフォールスルー（``ValueError`` も R3 narrow 対象）。
        """
        handler, new_creds = self._setup(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "youtube_automation.auth.oauth_handler.Credentials.from_authorized_user_file",
            MagicMock(side_effect=ValueError("required key missing")),
        )

        result = handler.authenticate()

        assert result is new_creds

    def test_should_log_warning_with_redacted_message_and_not_leak_token_path(
        self, tmp_path: Path, monkeypatch, caplog
    ):
        """Given ``OSError`` の str に ``_LEAKY_TOKEN_PATH`` が baked in
        When ``authenticate``
        Then warning ログに絶対パスが leak しない（path leak sentinel）。
        """
        handler, _ = self._setup(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "youtube_automation.auth.oauth_handler.Credentials.from_authorized_user_file",
            MagicMock(side_effect=OSError(2, "No such file", _LEAKY_TOKEN_PATH)),
        )
        caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

        handler.authenticate()

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("既存トークン読み込み失敗" in r.getMessage() for r in warnings), (
            "narrow 後の warning ログが出ていない"
        )
        for record in caplog.records:
            assert _LEAKY_TOKEN_PATH not in record.getMessage(), f"絶対パスが leak: {record.getMessage()!r}"

    def test_should_not_swallow_typeerror(self, tmp_path: Path, monkeypatch):
        """Given ``from_authorized_user_file`` が ``TypeError``（想定外）
        When ``authenticate``
        Then ``TypeError`` がそのまま伝播する。

        narrow ``(OSError, ValueError)`` の効果を検証する sentinel。
        """
        handler, _ = self._setup(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "youtube_automation.auth.oauth_handler.Credentials.from_authorized_user_file",
            MagicMock(side_effect=TypeError("argument type")),
        )

        with pytest.raises(TypeError):
            handler.authenticate()


# ===========================================================================
# 6. L144 — token refresh（#22〜#25）
# ===========================================================================


class TestAuthenticateRefresh:
    """L144: ``creds.refresh()`` の except narrow（R4）。"""

    def _setup_with_refresh_failure(self, tmp_path: Path, monkeypatch, *, refresh_side_effect: object):
        """expired token を読み込み、``refresh()`` が ``refresh_side_effect`` を投げるシナリオ。

        ``self.credentials = None`` 経由で新規認証フォールスルーが効くよう
        ``flow.run_local_server`` も mock 済み。
        """
        token_path = tmp_path / "token.json"
        token_path.write_text("{}")
        handler = _make_handler(tmp_path, token_path=token_path)

        expired_creds = _make_credentials(
            expired=True,
            valid=False,
            refresh_token="rt",
            refresh_side_effect=refresh_side_effect,
        )
        monkeypatch.setattr(
            "youtube_automation.auth.oauth_handler.Credentials.from_authorized_user_file",
            MagicMock(return_value=expired_creds),
        )
        new_creds = _make_credentials(valid=True, expired=False)
        flow = MagicMock()
        flow.run_local_server.return_value = new_creds
        monkeypatch.setattr(
            "youtube_automation.auth.oauth_handler.InstalledAppFlow.from_client_secrets_file",
            MagicMock(return_value=flow),
        )
        monkeypatch.setattr(handler, "_save_credentials", MagicMock())
        return handler, expired_creds, new_creds

    def test_should_run_new_auth_flow_on_refresh_error(self, tmp_path: Path, monkeypatch):
        """Given ``refresh()`` が ``RefreshError``
        When ``authenticate``
        Then 新規認証フォールスルーで ``flow.run_local_server`` の戻り値が credentials に。

        ``raise AuthError`` で recovery が壊れる falling-trap の明示禁止。
        """
        refresh_err = google.auth.exceptions.RefreshError("token expired")
        handler, _, new_creds = self._setup_with_refresh_failure(tmp_path, monkeypatch, refresh_side_effect=refresh_err)

        result = handler.authenticate()

        assert result is new_creds

    def test_should_not_raise_auth_error_on_refresh_error(self, tmp_path: Path, monkeypatch):
        """Given ``refresh()`` が ``RefreshError``
        When ``authenticate``
        Then ``AuthError`` は raise されない（contract 強化）。
        """
        refresh_err = google.auth.exceptions.RefreshError("token expired")
        handler, _, _ = self._setup_with_refresh_failure(tmp_path, monkeypatch, refresh_side_effect=refresh_err)

        try:
            handler.authenticate()
        except AuthError:
            pytest.fail("RefreshError 経路で AuthError が raise された (recovery 破壊)")

    def test_should_log_warning_with_redacted_message_on_refresh_failure(self, tmp_path: Path, monkeypatch, caplog):
        """Given ``refresh()`` が ``RefreshError``（メッセージに refresh_token=... が混入）
        When ``authenticate``
        Then warning ログが ``_redact`` 経由で出力され、生 token は残らない。
        """
        refresh_err = google.auth.exceptions.RefreshError(
            f"token rotation failed: refresh_token={_LEAKY_REFRESH_TOKEN}"
        )
        handler, _, _ = self._setup_with_refresh_failure(tmp_path, monkeypatch, refresh_side_effect=refresh_err)
        caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

        handler.authenticate()

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("token refresh 失敗" in r.getMessage() for r in warnings), "narrow 後の warning ログが出ていない"
        for record in caplog.records:
            assert _LEAKY_REFRESH_TOKEN not in record.getMessage()

    def test_should_not_swallow_non_refresh_error(self, tmp_path: Path, monkeypatch):
        """Given ``refresh()`` が ``ConnectionError``（``RefreshError`` 以外）
        When ``authenticate``
        Then narrow 対象外なので伝播。
        """
        handler, _, _ = self._setup_with_refresh_failure(
            tmp_path, monkeypatch, refresh_side_effect=ConnectionError("network down")
        )

        with pytest.raises(ConnectionError):
            handler.authenticate()


# ===========================================================================
# 7. L159 — 新規認証（#26〜#32）
# ===========================================================================


class TestAuthenticateNewAuth:
    """L159: ``flow.from_client_secrets_file`` / ``run_local_server`` の except narrow（R5）。"""

    def _setup_force_reauth(
        self,
        tmp_path: Path,
        monkeypatch,
        *,
        run_local_server_side_effect: object | None = None,
        from_secrets_side_effect: object | None = None,
    ):
        """``force_reauth=True`` 経路を発火させる handler を作る。

        ``client_secrets_file`` を ``_LEAKY_CLIENT_SECRETS`` に向け、
        path leak sentinel を効かせやすくしている。
        """
        client_secrets_path = Path(_LEAKY_CLIENT_SECRETS)
        handler = _make_handler(tmp_path, client_secrets_file=client_secrets_path)

        flow = MagicMock()
        if run_local_server_side_effect is not None:
            flow.run_local_server.side_effect = run_local_server_side_effect
        else:
            flow.run_local_server.return_value = _make_credentials(valid=True)

        if from_secrets_side_effect is not None:
            from_secrets = MagicMock(side_effect=from_secrets_side_effect)
        else:
            from_secrets = MagicMock(return_value=flow)
        monkeypatch.setattr(
            "youtube_automation.auth.oauth_handler.InstalledAppFlow.from_client_secrets_file",
            from_secrets,
        )
        save_spy = MagicMock()
        monkeypatch.setattr(handler, "_save_credentials", save_spy)
        return handler, save_spy

    def test_should_raise_auth_error_chained_from_oserror(self, tmp_path: Path, monkeypatch):
        """Given ``from_client_secrets_file`` が ``OSError``
        When ``authenticate(force_reauth=True)``
        Then ``AuthError`` を raise し、``__cause__`` が ``OSError``。
        """
        oserror = OSError(2, "No such file", _LEAKY_CLIENT_SECRETS)
        handler, _ = self._setup_force_reauth(tmp_path, monkeypatch, from_secrets_side_effect=oserror)

        with pytest.raises(AuthError) as exc_info:
            handler.authenticate(force_reauth=True)

        assert isinstance(exc_info.value.__cause__, OSError), (
            "AuthError の __cause__ が OSError ではない: 'from e' で chain されていない"
        )

    def test_should_raise_auth_error_chained_from_value_error(self, tmp_path: Path, monkeypatch):
        """Given ``from_client_secrets_file`` が ``ValueError``（client_type 不正）
        When ``authenticate(force_reauth=True)``
        Then ``AuthError`` でラップ。
        """
        ve = ValueError("client_type missing")
        handler, _ = self._setup_force_reauth(tmp_path, monkeypatch, from_secrets_side_effect=ve)

        with pytest.raises(AuthError) as exc_info:
            handler.authenticate(force_reauth=True)

        assert isinstance(exc_info.value.__cause__, ValueError)

    def test_should_raise_auth_error_chained_from_google_auth_error(self, tmp_path: Path, monkeypatch):
        """Given ``run_local_server`` が ``GoogleAuthError``
        When ``authenticate(force_reauth=True)``
        Then ``AuthError`` でラップ。
        """
        gae = google.auth.exceptions.GoogleAuthError("auth library error")
        handler, _ = self._setup_force_reauth(tmp_path, monkeypatch, run_local_server_side_effect=gae)

        with pytest.raises(AuthError) as exc_info:
            handler.authenticate(force_reauth=True)

        assert isinstance(exc_info.value.__cause__, google.auth.exceptions.GoogleAuthError)

    def test_should_log_error_with_redacted_message_and_not_leak_client_secrets_path(
        self, tmp_path: Path, monkeypatch, caplog
    ):
        """Given ``OSError`` の str に ``_LEAKY_CLIENT_SECRETS`` が baked in
        When ``authenticate(force_reauth=True)``
        Then ``error`` ログに client_secrets パスが leak しない（path leak sentinel）。
        """
        oserror = OSError(13, "Permission denied", _LEAKY_CLIENT_SECRETS)
        handler, _ = self._setup_force_reauth(tmp_path, monkeypatch, from_secrets_side_effect=oserror)
        caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

        with pytest.raises(AuthError):
            handler.authenticate(force_reauth=True)

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert any("OAuth 2.0 認証失敗" in r.getMessage() for r in errors)
        for record in caplog.records:
            assert _LEAKY_CLIENT_SECRETS not in record.getMessage()

    def test_should_not_call_save_credentials_when_flow_fails(self, tmp_path: Path, monkeypatch):
        """Given ``from_client_secrets_file`` が ``OSError``
        When ``authenticate(force_reauth=True)``
        Then ``_save_credentials`` は呼ばれない（失敗時に書き込みが走らない contract）。
        """
        oserror = OSError(13, "Permission denied", _LEAKY_CLIENT_SECRETS)
        handler, save_spy = self._setup_force_reauth(tmp_path, monkeypatch, from_secrets_side_effect=oserror)

        with pytest.raises(AuthError):
            handler.authenticate(force_reauth=True)

        assert save_spy.call_count == 0

    def test_should_not_swallow_typeerror(self, tmp_path: Path, monkeypatch):
        """Given ``run_local_server`` が ``TypeError``
        When ``authenticate(force_reauth=True)``
        Then narrow 対象外なので ``TypeError`` がそのまま伝播（``AuthError`` ラップしない）。
        """
        handler, _ = self._setup_force_reauth(tmp_path, monkeypatch, run_local_server_side_effect=TypeError("bad arg"))

        with pytest.raises(TypeError):
            handler.authenticate(force_reauth=True)

    def test_should_not_swallow_attribute_error_from_run_local_server(self, tmp_path: Path, monkeypatch):
        """Given ``run_local_server`` が ``AttributeError``（``WSGITimeoutError`` を simulate）
        When ``authenticate(force_reauth=True)``
        Then narrow ``(ValueError, OSError, GoogleAuthError)`` 対象外なので素通しで伝播。

        Python 3.13+ の ``wsgiref.simple_server.WSGITimeoutError``（``AttributeError`` サブクラス）
        は構成異常を示し、``AuthError`` でラップしても利用者の対処は変わらないため
        narrow philosophy に従い素通しが正しい contract（option A: catch 拡張は不採用）。
        """
        handler, _ = self._setup_force_reauth(
            tmp_path,
            monkeypatch,
            run_local_server_side_effect=AttributeError("WSGITimeoutError simulation"),
        )

        with pytest.raises(AttributeError):
            handler.authenticate(force_reauth=True)


# ===========================================================================
# 8. L202 — get_youtube_service / build()（#33〜#35）
# ===========================================================================


class TestGetYouTubeServiceBuild:
    """L202: ``build()`` の except narrow（R6）。"""

    def _setup(
        self,
        tmp_path: Path,
        monkeypatch,
        *,
        build_side_effect: object | None = None,
    ):
        """credentials を valid 化し、``build`` を制御可能にした handler を返す。"""
        handler = _make_handler(tmp_path)
        handler.credentials = _make_credentials(valid=True)
        if build_side_effect is not None:
            build_mock = MagicMock(side_effect=build_side_effect)
        else:
            build_mock = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("youtube_automation.auth.oauth_handler.build", build_mock)
        return handler, build_mock

    def test_should_raise_youtube_api_error_chained_via_from_http_error(self, tmp_path: Path, monkeypatch):
        """Given ``build()`` が ``HttpError``（503）
        When ``get_youtube_service``
        Then ``YouTubeAPIError`` を raise、``__cause__`` が ``HttpError``、``status_code`` が保持。

        既存パターン（``competitor_discovery.py:58`` 等）との統一を担保する。
        """
        http_err = _make_http_error(status=503)
        handler, _ = self._setup(tmp_path, monkeypatch, build_side_effect=http_err)

        with pytest.raises(YouTubeAPIError) as exc_info:
            handler.get_youtube_service()

        assert isinstance(exc_info.value.__cause__, HttpError)
        assert exc_info.value.status_code == 503

    def test_should_preserve_context_message_in_youtube_api_error(self, tmp_path: Path, monkeypatch):
        """Given ``build()`` が ``HttpError``
        When ``get_youtube_service``
        Then ``YouTubeAPIError.message`` に context 文言（"YouTube" を含む）が乗る。
        """
        http_err = _make_http_error(status=403, reason="Forbidden")
        handler, _ = self._setup(tmp_path, monkeypatch, build_side_effect=http_err)

        with pytest.raises(YouTubeAPIError) as exc_info:
            handler.get_youtube_service()

        assert "YouTube" in str(exc_info.value), f"context が消えた: {exc_info.value!s}"

    def test_should_not_swallow_non_http_error(self, tmp_path: Path, monkeypatch):
        """Given ``build()`` が ``RuntimeError``
        When ``get_youtube_service``
        Then narrow 対象外なので伝播（旧 ``except Exception`` の握りつぶし禁止）。
        """
        handler, _ = self._setup(tmp_path, monkeypatch, build_side_effect=RuntimeError("network glitch"))

        with pytest.raises(RuntimeError):
            handler.get_youtube_service()


# ===========================================================================
# 9. L230 — test_connection（#36〜#43）
# ===========================================================================


class TestTestConnection:
    """L230: ``test_connection`` の except narrow（R7）。"""

    def _setup(
        self,
        tmp_path: Path,
        monkeypatch,
        *,
        get_service_side_effect: object | None = None,
        items: list | None = None,
    ):
        """``get_youtube_service`` を制御可能にした handler。"""
        handler = _make_handler(tmp_path)
        handler.credentials = _make_credentials(valid=True)

        if get_service_side_effect is not None:
            monkeypatch.setattr(
                handler,
                "get_youtube_service",
                MagicMock(side_effect=get_service_side_effect),
            )
            return handler

        service = MagicMock()
        default_items = [
            {
                "snippet": {"title": "X"},
                "statistics": {"subscriberCount": "1"},
            }
        ]
        service.channels.return_value.list.return_value.execute.return_value = {
            "items": items if items is not None else default_items
        }
        monkeypatch.setattr(handler, "get_youtube_service", MagicMock(return_value=service))
        return handler

    def test_should_return_false_on_http_error(self, tmp_path: Path, monkeypatch):
        """Given ``HttpError``
        When ``test_connection``
        Then ``False``。
        """
        handler = self._setup(tmp_path, monkeypatch, get_service_side_effect=_make_http_error(status=500))
        assert handler.test_connection() is False

    def test_should_return_false_on_auth_error_from_authenticate(self, tmp_path: Path, monkeypatch):
        """Given ``authenticate`` 経由の ``AuthError``
        When ``test_connection``
        Then ``False``（bool contract 維持）。
        """
        handler = self._setup(
            tmp_path,
            monkeypatch,
            get_service_side_effect=AuthError("authenticate failed"),
        )
        assert handler.test_connection() is False

    def test_should_return_false_on_youtube_api_error(self, tmp_path: Path, monkeypatch):
        """Given ``YouTubeAPIError``
        When ``test_connection``
        Then ``False``。
        """
        handler = self._setup(
            tmp_path,
            monkeypatch,
            get_service_side_effect=YouTubeAPIError("api down"),
        )
        assert handler.test_connection() is False

    def test_should_return_false_on_google_auth_error(self, tmp_path: Path, monkeypatch):
        """Given ``GoogleAuthError``
        When ``test_connection``
        Then ``False``。
        """
        handler = self._setup(
            tmp_path,
            monkeypatch,
            get_service_side_effect=google.auth.exceptions.GoogleAuthError("auth lib"),
        )
        assert handler.test_connection() is False

    def test_should_return_false_on_oserror(self, tmp_path: Path, monkeypatch):
        """Given ``OSError``
        When ``test_connection``
        Then ``False``。
        """
        handler = self._setup(
            tmp_path,
            monkeypatch,
            get_service_side_effect=OSError(2, "X", _LEAKY_TOKEN_PATH),
        )
        assert handler.test_connection() is False

    def test_should_log_error_with_redacted_message_and_not_leak_paths(self, tmp_path: Path, monkeypatch, caplog):
        """Given ``token_file`` / ``client_secrets_file`` 双方が leak path に設定された handler
        When ``test_connection`` で OSErrno + literal 双方の leak が起きうる例外
        Then どちらのパスも error ログに leak しない。
        """
        handler = self._setup(tmp_path, monkeypatch)
        handler.token_file = Path(_LEAKY_TOKEN_PATH)
        handler.client_secrets_file = Path(_LEAKY_CLIENT_SECRETS)
        leak_err = OSError(
            13,
            f"Permission denied at {_LEAKY_CLIENT_SECRETS}",
            _LEAKY_TOKEN_PATH,
        )
        monkeypatch.setattr(handler, "get_youtube_service", MagicMock(side_effect=leak_err))
        caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

        handler.test_connection()

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert any("API 接続テスト失敗" in r.getMessage() for r in errors)
        for record in caplog.records:
            msg = record.getMessage()
            assert _LEAKY_TOKEN_PATH not in msg, f"token_file path leak: {msg!r}"
            assert _LEAKY_CLIENT_SECRETS not in msg, f"client_secrets path leak: {msg!r}"

    def test_should_not_swallow_non_listed_exception(self, tmp_path: Path, monkeypatch):
        """Given narrow ``(HttpError, AuthError, YouTubeAPIError, GoogleAuthError, OSError)`` 対象外
        When ``test_connection``
        Then 例外がそのまま伝播（旧 ``except Exception`` の握りつぶし禁止）。
        """
        handler = self._setup(
            tmp_path,
            monkeypatch,
            get_service_side_effect=RuntimeError("unexpected"),
        )

        with pytest.raises(RuntimeError):
            handler.test_connection()

    def test_should_return_false_when_items_list_is_empty(self, tmp_path: Path, monkeypatch):
        """Given API レスポンスの ``items`` が空
        When ``test_connection``
        Then ``False``（既存正常系 falsy path の回帰保護）。
        """
        handler = self._setup(tmp_path, monkeypatch, items=[])

        assert handler.test_connection() is False
