"""issue #192: ``oauth_handler.main()`` の except narrow / logger 化テスト。

検証対象:

- 既知例外は CLI 境界で処理し、未知例外は捕捉せず呼び出し元へ伝播すること。
- ドメイン例外経路は raw traceback を出さず、ログメッセージに redaction が行われること。
- 想定外例外は CLI 境界で処理せず、元の例外型とメッセージを保つこと。
- ``KeyboardInterrupt`` で exit code 130、既知例外で exit code 1 を返すこと。
- 正常系では ``sys.exit`` が呼ばれず終了すること（既存挙動の回帰保護）。

テスト方針（既存 ``test_oauth_handler_exceptions.py`` 準拠）:

- ``YouTubeOAuthHandler`` を ``monkeypatch`` でフェイク差し替えし、
  ``main()`` の try/except 構造のみを単離して検証する。
- ``caplog`` で logger 経由のメッセージ・redaction 効果を検証する。
- sentinel テストで ``KeyboardInterrupt`` が ``Exception`` 側 catch に
  飲み込まれていないことを exit code 経由で保証する。
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from youtube_automation.infrastructure.auth import youtube as oauth_handler
from youtube_automation.infrastructure.errors import AuthError, ConfigError, ValidationError, YouTubeAPIError

# leak sentinel は `test_oauth_handler_exceptions.py` と同値を使う
# （モジュール跨ぎでヘルパ共有を増やすとテスト間の依存が広がるため、定数だけ重複させる）。
_LEAKY_ACCESS_TOKEN = "ya29.A0AbCdEfGhIjKlMnOpQrStUvWxYz123456"
_LEAKY_TOKEN_PATH = "/Users/leak-canary/auth/token.json"
_LEAKY_CLIENT_SECRETS = "/Users/leak-canary/auth/client_secrets.json"

_LOGGER_NAME = "youtube_automation.infrastructure.auth.youtube"


def _install_fake_handler(
    monkeypatch,
    *,
    init_side_effect: object | None = None,
    authenticate_side_effect: object | None = None,
    test_connection_side_effect: object | None = None,
    test_connection_return: bool = True,
) -> MagicMock:
    """``YouTubeOAuthHandler`` を fake に差し替える。

    ``main()`` の 3 ステップ (``__init__`` / ``authenticate`` / ``test_connection``)
    のどこで例外を投げるかを引数で制御する。戻り値はインスタンス mock（呼び出し検証用）。
    """
    instance = MagicMock()
    if authenticate_side_effect is not None:
        instance.authenticate.side_effect = authenticate_side_effect
    if test_connection_side_effect is not None:
        instance.test_connection.side_effect = test_connection_side_effect
    else:
        instance.test_connection.return_value = test_connection_return

    factory = MagicMock()
    if init_side_effect is not None:
        factory.side_effect = init_side_effect
    else:
        factory.return_value = instance

    monkeypatch.setattr(oauth_handler, "YouTubeOAuthHandler", factory)
    return instance


# ===========================================================================
# 1. 正常系: sys.exit が呼ばれない（既存挙動の回帰保護）
# ===========================================================================


class TestMainSuccessPath:
    """``main()`` の正常系 contract。"""

    def test_should_not_call_sys_exit_on_successful_run(self, monkeypatch):
        """Given handler / authenticate / test_connection が成功
        When ``main()``
        Then ``sys.exit`` を呼ばない（戻り値 None で関数を抜ける）。
        """
        _install_fake_handler(monkeypatch, test_connection_return=True)

        # sys.exit が呼ばれたらテストを fail させるための sentinel
        monkeypatch.setattr(oauth_handler.sys, "exit", MagicMock(side_effect=AssertionError("sys.exit が呼ばれた")))

        oauth_handler.main([])  # 例外を投げずに完走すれば OK

    def test_should_not_call_sys_exit_when_test_connection_returns_false(self, monkeypatch):
        """Given ``test_connection`` が ``False`` を返す（bool 経路）
        When ``main()``
        Then ``sys.exit`` を呼ばない（既存挙動: print のみで exit 0 終了）。
        """
        _install_fake_handler(monkeypatch, test_connection_return=False)
        monkeypatch.setattr(oauth_handler.sys, "exit", MagicMock(side_effect=AssertionError("sys.exit が呼ばれた")))

        oauth_handler.main([])


# ===========================================================================
# 2. KeyboardInterrupt 経路: exit code 130
# ===========================================================================


class TestMainKeyboardInterrupt:
    """``KeyboardInterrupt`` の独立 catch contract（推奨対応 #3）。"""

    def test_should_exit_with_code_130_on_keyboard_interrupt(self, monkeypatch):
        """Given ``authenticate()`` が ``KeyboardInterrupt``
        When ``main()``
        Then ``sys.exit(130)`` を呼ぶ（UNIX 慣例 128 + SIGINT=2）。
        """
        _install_fake_handler(monkeypatch, authenticate_side_effect=KeyboardInterrupt())

        with pytest.raises(SystemExit) as exc_info:
            oauth_handler.main([])

        assert exc_info.value.code == 130

    def test_should_exit_130_even_when_keyboard_interrupt_raised_in_init(self, monkeypatch):
        """Given ``YouTubeOAuthHandler()`` の構築中に ``KeyboardInterrupt``
        When ``main()``
        Then exit 130（auth_handler 構築前でも catch される）。
        """
        _install_fake_handler(monkeypatch, init_side_effect=KeyboardInterrupt())

        with pytest.raises(SystemExit) as exc_info:
            oauth_handler.main([])

        assert exc_info.value.code == 130


# ===========================================================================
# 3. ドメイン例外経路: ドメイン例外それぞれで exit 1 + logger.error + redaction
# ===========================================================================


class TestMainDomainExceptions:
    """ドメイン例外の narrow catch（推奨対応 #1, #2）。"""

    @pytest.mark.parametrize(
        "exc",
        [
            AuthError("OAuth 認証に失敗しました"),
            ConfigError("client_secrets.json が見つかりません"),
            ValidationError("client_secrets.json は通常ファイルである必要があります"),
            YouTubeAPIError("YouTube Data API 接続失敗"),
            OSError(13, "Permission denied", "/tmp/dummy"),
        ],
        ids=["AuthError", "ConfigError", "ValidationError", "YouTubeAPIError", "OSError"],
    )
    def test_should_exit_with_code_1_on_each_domain_exception(self, monkeypatch, exc):
        """Given 4 ドメイン例外のいずれかが ``authenticate()`` から raise
        When ``main()``
        Then ``sys.exit(1)``。
        """
        _install_fake_handler(monkeypatch, authenticate_side_effect=exc)

        with pytest.raises(SystemExit) as exc_info:
            oauth_handler.main([])

        assert exc_info.value.code == 1

    def test_should_log_exception_with_redacted_message_on_auth_error(self, monkeypatch, caplog):
        """Given ``AuthError`` の message に token 値が混入
        When ``main()``
        Then logger に ``CLI 実行失敗`` レベル ERROR + traceback が出力され、
              token 値は redaction で除去される。
        """
        leaky_msg = f"token rotation failed: {_LEAKY_ACCESS_TOKEN}"
        _install_fake_handler(monkeypatch, authenticate_side_effect=AuthError(leaky_msg))
        caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

        with pytest.raises(SystemExit):
            oauth_handler.main([])

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert any("CLI 実行失敗" in r.getMessage() for r in errors), "narrow catch の error ログが出ていない"
        assert all(r.exc_info is None for r in errors), "ドメイン例外経路で raw traceback が記録されている"
        # token leak 防止
        for record in caplog.records:
            assert _LEAKY_ACCESS_TOKEN not in record.getMessage()

    def test_should_log_exception_with_redacted_path_on_oserror(self, monkeypatch, caplog):
        """Given ``OSError`` の str に絶対パスが含まれる（OSErrno 形式）
        When ``main()``
        Then error ログに絶対パスが leak しない（``_OSERRNO_PATH_RE`` 経由）。
        """
        leaky_oserror = OSError(2, "No such file or directory", _LEAKY_TOKEN_PATH)
        _install_fake_handler(monkeypatch, authenticate_side_effect=leaky_oserror)
        caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

        with pytest.raises(SystemExit):
            oauth_handler.main([])

        for record in caplog.records:
            assert _LEAKY_TOKEN_PATH not in record.getMessage(), (
                f"OSError 経路で絶対パスが leak: {record.getMessage()!r}"
            )

    def test_should_log_validation_error_without_leaking_client_secrets_path(self, monkeypatch, caplog):
        """Given ``ValidationError`` の message に client_secrets 絶対パスが混入
        When ``main()``
        Then handler 属性を使った redaction が効き、raw traceback も出さない。
        """
        instance = _install_fake_handler(
            monkeypatch,
            authenticate_side_effect=ValidationError(
                f"client_secrets.json は通常ファイルである必要があります: {_LEAKY_CLIENT_SECRETS}"
            ),
        )
        instance.client_secrets_file = _LEAKY_CLIENT_SECRETS
        instance.token_file = _LEAKY_TOKEN_PATH
        caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

        with pytest.raises(SystemExit) as exc_info:
            oauth_handler.main([])

        assert exc_info.value.code == 1
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert errors
        assert all(r.exc_info is None for r in errors)
        for record in caplog.records:
            assert _LEAKY_CLIENT_SECRETS not in record.getMessage()
            assert _LEAKY_TOKEN_PATH not in record.getMessage()
        assert any("<redacted-path>" in r.getMessage() for r in errors)

    def test_should_catch_config_error_raised_during_handler_init(self, monkeypatch):
        """Given ``YouTubeOAuthHandler()`` の構築段階で ``ConfigError``
        When ``main()``
        Then catch 句に含まれ ``sys.exit(1)``（auth_handler 構築前経路の保護）。
        """
        _install_fake_handler(monkeypatch, init_side_effect=ConfigError("op read failed"))

        with pytest.raises(SystemExit) as exc_info:
            oauth_handler.main([])

        assert exc_info.value.code == 1

    def test_should_log_cli_failure_for_validation_error(self, monkeypatch, caplog):
        """Given ``ValidationError`` が authenticate から raise
        When ``main()``
        Then 最終 fallback ではなく通常ドメイン例外として ``CLI 実行失敗`` に記録される。
        """
        _install_fake_handler(monkeypatch, authenticate_side_effect=ValidationError("invalid client_secrets"))
        caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)

        with pytest.raises(SystemExit) as exc_info:
            oauth_handler.main([])

        assert exc_info.value.code == 1
        assert any("CLI 実行失敗" in r.getMessage() for r in caplog.records)
        assert not any("想定外" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("exception_type", [RuntimeError, TypeError, ValueError])
class TestMainUnexpectedException:
    def test_should_propagate_unexpected_exception(self, exception_type, monkeypatch):
        sentinel = "/private/credential-store/oauth-canary"
        _install_fake_handler(monkeypatch, authenticate_side_effect=exception_type(sentinel))

        with pytest.raises(exception_type, match="oauth-canary"):
            oauth_handler.main([])


@pytest.mark.parametrize(
    "message",
    [
        "client_secret: oauth-secret",
        '{"client_secret": "oauth-secret"}',
        "authorization=Bearer oauth-secret",
        "token: oauth-secret",
        '{"token": "oauth-secret"}',
        "token=oauth-secret",
    ],
)
def test_should_redact_sensitive_field_formats_in_domain_error(message, monkeypatch, caplog):
    _install_fake_handler(monkeypatch, authenticate_side_effect=AuthError(message))
    caplog.set_level(logging.ERROR, logger=_LOGGER_NAME)

    with pytest.raises(SystemExit) as exc_info:
        oauth_handler.main([])

    assert exc_info.value.code == 1
    messages = [record.getMessage() for record in caplog.records]
    assert messages
    assert all("oauth-secret" not in message for message in messages)
    assert all("<redacted-token>" in message for message in messages)
