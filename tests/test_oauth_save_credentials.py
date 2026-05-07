"""``YouTubeOAuthHandler._save_credentials`` のユニットテスト（issue #149）。

検証する 4 ケース（plan §6 のテストカバレッジ要件）:

1. 新規ファイル作成時に **0o600** で作成される
2. 既存 0o644 ファイル上書き時にも **0o600** に矯正される（``os.chmod`` 保険）
3. 書き込み失敗時に ``ConfigError`` を raise し、原因の ``OSError`` が
   ``__cause__`` に保持される（``raise ... from e`` の検証）
4. ``ConfigError`` メッセージに復旧ヒント
   「親ディレクトリの書き込み権限と空き容量を確認」が含まれる

外部 OAuth フローや 1Password 等は ``token_path`` 引数を使って
``_save_credentials`` の I/O だけを単離して検証する。
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from youtube_automation.auth.oauth_handler import YouTubeOAuthHandler
from youtube_automation.utils.exceptions import ConfigError

# ---------------------------------------------------------------------------
# テストヘルパー
# ---------------------------------------------------------------------------


def _build_handler(token_path: Path) -> YouTubeOAuthHandler:
    """``_save_credentials`` だけを叩くための最小構成 handler を作る。

    ``credentials.to_json()`` が文字列を返すよう mock 済み。
    OAuth フローや client_secrets には触らない。
    """
    handler = YouTubeOAuthHandler(token_path=token_path)
    mock_creds = MagicMock()
    mock_creds.to_json.return_value = '{"token": "fake-token"}'
    handler.credentials = mock_creds
    return handler


def _file_mode(path: Path) -> int:
    """ファイルのパーミッションビット（lower 9 bits）を返す。"""
    return stat.S_IMODE(path.stat().st_mode)


# ---------------------------------------------------------------------------
# _save_credentials のファイル権限テスト
# ---------------------------------------------------------------------------


class TestSaveCredentialsFileMode:
    """token ファイルの権限が 0o600 で書き込まれることの検証。"""

    def test_new_file_is_created_with_0o600(self, tmp_path: Path):
        """Given token ファイルが存在しない
        When ``_save_credentials`` を実行
        Then 新規作成されたファイルのパーミッションが 0o600 になる。

        umask 依存の ``open(..., "w")``（0o644 になりうる）を
        ``os.open(..., 0o600)`` に置き換えた効果を担保する（R1）。
        """
        token_path = tmp_path / "token.json"
        handler = _build_handler(token_path)

        handler._save_credentials()

        assert token_path.exists(), "token ファイルが作成されていない"
        assert _file_mode(token_path) == 0o600, (
            f"新規 token ファイルの mode が 0o600 でない: {oct(_file_mode(token_path))}"
        )

    def test_existing_0o644_file_is_chmoded_to_0o600(self, tmp_path: Path):
        """Given 既存 token ファイルが 0o644（world-readable）で存在
        When ``_save_credentials`` を実行（上書き保存）
        Then 保存後のパーミッションが 0o600 に矯正される。

        ``O_TRUNC`` は既存ファイルの mode を変更しないため、
        ``os.chmod`` の保険が必須（R2）。
        """
        token_path = tmp_path / "token.json"
        token_path.write_text("{}")
        os.chmod(token_path, 0o644)
        assert _file_mode(token_path) == 0o644, "前提セットアップ失敗"

        handler = _build_handler(token_path)
        handler._save_credentials()

        assert _file_mode(token_path) == 0o600, (
            f"既存 0o644 ファイルが 0o600 に矯正されていない: {oct(_file_mode(token_path))}"
        )

    def test_credentials_json_is_written_to_file(self, tmp_path: Path):
        """Given ``credentials.to_json()`` が JSON 文字列を返す
        When ``_save_credentials``
        Then その文字列がそのまま token ファイルに書かれる。

        ファイル権限の修正で内容書き込みが壊れていないことの sanity check。
        """
        token_path = tmp_path / "token.json"
        handler = _build_handler(token_path)

        handler._save_credentials()

        assert token_path.read_text() == '{"token": "fake-token"}'


# ---------------------------------------------------------------------------
# _save_credentials の例外伝播テスト
# ---------------------------------------------------------------------------


class TestSaveCredentialsErrorPropagation:
    """書き込み失敗時に握りつぶさず ``ConfigError`` を raise することの検証。"""

    def test_missing_parent_directory_raises_config_error(self, tmp_path: Path):
        """Given 親ディレクトリが存在しない token_path
        When ``_save_credentials``
        Then ``ConfigError`` が raise される（旧実装の握りつぶしを禁止）。

        旧 ``except Exception: print(...)`` で黙って成功扱いになると
        次回起動で毎回ブラウザ認証が走る運用障害になる。R3 の検証。
        """
        # 存在しない親ディレクトリ配下のパス
        token_path = tmp_path / "does-not-exist" / "token.json"
        handler = _build_handler(token_path)

        with pytest.raises(ConfigError):
            handler._save_credentials()

    def test_config_error_chains_original_oserror_via_from(self, tmp_path: Path):
        """Given 書き込み失敗（親ディレクトリ不在）
        When ``ConfigError`` が raise される
        Then ``__cause__`` に元の ``OSError`` が保持されている
        （``raise ConfigError(...) from e`` の検証）。

        例外チェーンを切ると stacktrace から root cause が消えてデバッグ困難になる。
        """
        token_path = tmp_path / "does-not-exist" / "token.json"
        handler = _build_handler(token_path)

        with pytest.raises(ConfigError) as exc_info:
            handler._save_credentials()

        assert exc_info.value.__cause__ is not None, "ConfigError の __cause__ が None: 'from e' で chain されていない"
        assert isinstance(exc_info.value.__cause__, OSError), (
            f"__cause__ が OSError サブクラスでない: {type(exc_info.value.__cause__)}"
        )

    def test_config_error_message_contains_recovery_hint(self, tmp_path: Path):
        """Given 書き込み失敗
        When ``ConfigError`` のメッセージを確認
        Then 「親ディレクトリの書き込み権限と空き容量を確認」のヒントが含まれる。

        order.md で明記された UX 要求（R4）。利用者が何を確認すべきか
        メッセージ単独で分かるようにする。
        """
        token_path = tmp_path / "does-not-exist" / "token.json"
        handler = _build_handler(token_path)

        with pytest.raises(ConfigError) as exc_info:
            handler._save_credentials()

        message = str(exc_info.value)
        assert "親ディレクトリの書き込み権限と空き容量を確認" in message, (
            f"復旧ヒントがメッセージに含まれない: {message!r}"
        )

    def test_config_error_message_contains_token_file_path(self, tmp_path: Path):
        """Given 書き込み失敗
        When ``ConfigError`` のメッセージ
        Then どの path で失敗したか分かるよう token_file のパスが含まれる。

        order.md の推奨対応コード ``f"認証トークン保存失敗: {self.token_file} ..."``
        に対応する。
        """
        token_path = tmp_path / "does-not-exist" / "token.json"
        handler = _build_handler(token_path)

        with pytest.raises(ConfigError) as exc_info:
            handler._save_credentials()

        message = str(exc_info.value)
        assert str(token_path) in message, f"token_file path がメッセージに含まれない: {message!r}"

    def test_typeerror_is_not_swallowed(self, tmp_path: Path):
        """Given ``credentials.to_json()`` が文字列以外を返す（呼び元バグ）
        When ``_save_credentials``
        Then ``TypeError`` がそのまま伝播する（``OSError`` だけ ``ConfigError``
        に変換し、それ以外は握りつぶさない）。

        旧 ``except Exception`` で隠れていた呼び元バグを表面化させる
        （R3 の except スコープを ``OSError`` に絞った効果）。
        """
        token_path = tmp_path / "token.json"
        handler = _build_handler(token_path)
        # to_json が非文字列を返す = file.write が TypeError を投げる
        handler.credentials.to_json.return_value = MagicMock()

        with pytest.raises(TypeError):
            handler._save_credentials()
