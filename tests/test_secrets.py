"""utils/secrets.py のユニットテスト。

検証する 3 経路:
1. os.environ に既にあれば op を呼ばずにそれを返す
2. os.environ に無く op がある場合は op read で取得して返す（os.environ への書き戻しは行わない）
3. どちらも失敗したら ConfigError を raise する
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from youtube_automation.utils import secrets as secrets_module
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.secrets import (
    _SECRET_REFS,
    get_client_secrets_path,
    get_secret,
    reset_cache,
)

_TEST_SECRET = "CLIENT_SECRETS_JSON"
_MANAGED_SECRETS = ("CLIENT_SECRETS_JSON", "OPENAI_API_KEY")


@pytest.fixture(autouse=True)
def clean_env():
    """各テスト前後で対象シークレットと lru_cache をクリーンにする"""
    saved: dict[str, str | None] = {name: os.environ.pop(name, None) for name in _MANAGED_SECRETS}
    reset_cache()
    yield
    reset_cache()
    for name, value in saved.items():
        if value is not None:
            os.environ[name] = value
        else:
            os.environ.pop(name, None)


class TestGetSecret:
    def test_returns_from_environ_when_present(self):
        """既に os.environ にあれば op を呼ばずにそれを返す"""
        os.environ[_TEST_SECRET] = "from-env-12345"
        with patch("youtube_automation.utils.secrets.subprocess.run") as mock_run:
            value = get_secret(_TEST_SECRET)
        assert value == "from-env-12345"
        mock_run.assert_not_called()

    def test_falls_back_to_op_read_when_environ_empty(self):
        """os.environ に無く op が成功すれば op read の値を返す"""
        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=["op", "read", "..."],
                returncode=0,
                stdout="from-op-67890\n",
                stderr="",
            )
            value = get_secret(_TEST_SECRET)
        assert value == "from-op-67890"
        mock_run.assert_called_once()

    def test_op_read_result_is_not_written_to_environ(self):
        """op read で取得した値は os.environ にセットされない（global env 注入禁止: Issue #163）"""
        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=["op", "read", "..."],
                returncode=0,
                stdout="op-only-value\n",
                stderr="",
            )
            get_secret(_TEST_SECRET)
        assert os.environ.get(_TEST_SECRET) is None

    def test_raises_config_error_when_op_unavailable_and_environ_empty(self):
        """op が無く os.environ も空なら ConfigError"""
        with patch("youtube_automation.utils.secrets.shutil.which", return_value=None):
            with pytest.raises(ConfigError, match=_TEST_SECRET):
                get_secret(_TEST_SECRET)

    def test_raises_config_error_when_op_read_fails(self):
        """op はあるが op read が失敗したら ConfigError"""
        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd=["op", "read", "..."])
            with pytest.raises(ConfigError, match=_TEST_SECRET):
                get_secret(_TEST_SECRET)

    def test_raises_config_error_for_unknown_secret_name(self):
        """未登録のシークレット名は ConfigError"""
        with pytest.raises(ConfigError, match="未登録"):
            get_secret("UNKNOWN_SECRET")

    def test_lru_cache_avoids_repeated_op_reads(self):
        """同一名で 2 回呼んでも op read は 1 回しか呼ばれない"""
        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=["op", "read", "..."],
                returncode=0,
                stdout="cached\n",
                stderr="",
            )
            get_secret(_TEST_SECRET)
            get_secret(_TEST_SECRET)
        mock_run.assert_called_once()


# ---------- OPENAI_API_KEY (Issue #67: gpt-image-2 サポート) ----------


class TestOpenAIApiKeyRegistered:
    """OPENAI_API_KEY が `_SECRET_REFS` に登録され、既存 3 経路が機能することを確認する。"""

    def test_openai_api_key_is_registered_in_secret_refs(self):
        """Given _SECRET_REFS
        When OPENAI_API_KEY を引く
        Then 1Password 参照 URI が登録されている。
        """
        assert "OPENAI_API_KEY" in _SECRET_REFS, "OPENAI_API_KEY が _SECRET_REFS に未登録"
        ref = _SECRET_REFS["OPENAI_API_KEY"]
        # op:// スキームの参照 URI であること
        assert ref.startswith("op://"), f"1Password 参照 URI 形式でない: {ref}"

    def test_openai_api_key_returns_from_environ_when_present(self):
        """既に os.environ にあれば op を呼ばずにそれを返す。"""
        os.environ["OPENAI_API_KEY"] = "sk-from-env-12345"
        with patch("youtube_automation.utils.secrets.subprocess.run") as mock_run:
            value = get_secret("OPENAI_API_KEY")
        assert value == "sk-from-env-12345"
        mock_run.assert_not_called()

    def test_openai_api_key_falls_back_to_op_read(self):
        """os.environ に無く op が成功すれば op read の値を返す。"""
        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=["op", "read", "..."],
                returncode=0,
                stdout="sk-from-op-67890\n",
                stderr="",
            )
            value = get_secret("OPENAI_API_KEY")
        assert value == "sk-from-op-67890"
        mock_run.assert_called_once()

    def test_openai_api_key_raises_config_error_when_unavailable(self):
        """op が無く os.environ も空なら ConfigError。"""
        with patch("youtube_automation.utils.secrets.shutil.which", return_value=None):
            with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
                get_secret("OPENAI_API_KEY")


# ---------- Issue #110: 帯域モニタリング用シークレット ----------


class TestStreamingSecretsRegistered:
    """VULTR_API_KEY / STREAM_WEBHOOK_URL / DISCORD_WEBHOOK_URL の 3 シークレットが
    `_SECRET_REFS` に登録され、4 経路 (登録確認 / env / op-fallback / fail) が
    そのまま機能することを確認する。
    """

    @pytest.fixture(autouse=True)
    def _clean(self):
        for name in ("VULTR_API_KEY", "STREAM_WEBHOOK_URL", "DISCORD_WEBHOOK_URL"):
            os.environ.pop(name, None)
        reset_cache()
        yield
        for name in ("VULTR_API_KEY", "STREAM_WEBHOOK_URL", "DISCORD_WEBHOOK_URL"):
            os.environ.pop(name, None)
        reset_cache()

    @pytest.mark.parametrize("name", ["VULTR_API_KEY", "STREAM_WEBHOOK_URL", "DISCORD_WEBHOOK_URL"])
    def test_secret_is_registered_in_secret_refs(self, name: str):
        """Given _SECRET_REFS
        When 引く
        Then 1Password 参照 URI (op://) として登録されている。
        """
        assert name in _SECRET_REFS, f"{name} が _SECRET_REFS に未登録"
        ref = _SECRET_REFS[name]
        assert ref.startswith("op://"), f"1Password 参照 URI 形式でない: {ref}"

    @pytest.mark.parametrize("name", ["VULTR_API_KEY", "STREAM_WEBHOOK_URL", "DISCORD_WEBHOOK_URL"])
    def test_returns_from_environ_when_present(self, name: str):
        """既に os.environ にあれば op を呼ばずにそれを返す。"""
        os.environ[name] = f"value-of-{name}"
        with patch("youtube_automation.utils.secrets.subprocess.run") as mock_run:
            value = get_secret(name)
        assert value == f"value-of-{name}"
        mock_run.assert_not_called()

    @pytest.mark.parametrize("name", ["VULTR_API_KEY", "STREAM_WEBHOOK_URL", "DISCORD_WEBHOOK_URL"])
    def test_falls_back_to_op_read(self, name: str):
        """env に無く op が成功すれば op read の値を返す。"""
        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=["op", "read", "..."],
                returncode=0,
                stdout=f"from-op-{name}\n",
                stderr="",
            )
            value = get_secret(name)
        assert value == f"from-op-{name}"
        mock_run.assert_called_once()

    @pytest.mark.parametrize("name", ["VULTR_API_KEY", "STREAM_WEBHOOK_URL", "DISCORD_WEBHOOK_URL"])
    def test_raises_config_error_when_unavailable(self, name: str):
        """env も op も空なら ConfigError。"""
        with patch("youtube_automation.utils.secrets.shutil.which", return_value=None):
            with pytest.raises(ConfigError, match=name):
                get_secret(name)


# ---------- Issue #150: client_secrets tempfile の atexit クリーンアップ ----------


_TEST_JSON_PAYLOAD = '{"installed":{"client_id":"x"}}'
_EXPECTED_PREFIX = "client_secrets_"
_EXPECTED_SUFFIX = ".json"
_EXPECTED_MODE = 0o600


class TestGetClientSecretsPath:
    """`get_client_secrets_path` の振る舞いを検証する。

    plan.md / test-design.md に基づく 12 ケース:
      1. 初回呼び出しで実在する tempfile への Path を返す
      2. 同一プロセス内 2 回呼ぶと同じ Path / get_secret 1 回のみ
      3. キャッシュミス時に atexit.register がちょうど 1 回呼ばれる
      4. 作成された tempfile のパーミッションは 0o600
      5. ファイル名が `client_secrets_` prefix / `.json` suffix
      6. キャッシュヒット時に atexit.register が再度呼ばれない
      7. tempfile の中身が get_secret の戻り値と一致する
      8. 登録された atexit ハンドラを実行すると tempfile が削除される
      9. atexit ハンドラ実行時にファイルが既に消えていても例外を投げない
     10. キャッシュされたファイルが消失していたら新規作成する
     11. get_secret が ConfigError を raise したら伝播し、tempfile を作らない
     12. get_secret が raise したとき atexit.register が呼ばれない
    """

    @pytest.fixture(autouse=True)
    def clean_client_secrets_tempfile(self):
        """テスト前後でモジュール変数 `_client_secrets_tempfile` を必ず None に戻し、
        実 tempfile が残っていれば削除する。テスト独立性確保のため。
        """
        prev = secrets_module._client_secrets_tempfile
        secrets_module._client_secrets_tempfile = None
        yield
        leftover = secrets_module._client_secrets_tempfile
        secrets_module._client_secrets_tempfile = prev
        if leftover is not None and leftover.exists():
            try:
                os.unlink(leftover)
            except OSError:
                pass

    # ---- Case 1 ----
    def test_returns_path_to_existing_tempfile_on_first_call(self):
        """Given get_secret がモック JSON を返す
        When get_client_secrets_path() を初めて呼ぶ
        Then 実在する tempfile への Path を返す
        """
        with patch("youtube_automation.utils.secrets.get_secret", return_value=_TEST_JSON_PAYLOAD):
            path = get_client_secrets_path()
        assert isinstance(path, Path)
        assert path.exists()

    # ---- Case 2 ----
    def test_returns_same_path_and_calls_get_secret_once_on_repeat_calls(self):
        """Given 同一プロセス内で 2 回呼び出す
        When 2 回目の get_client_secrets_path()
        Then 同じ Path が返り、get_secret は 1 回しか呼ばれない
        """
        with patch("youtube_automation.utils.secrets.get_secret", return_value=_TEST_JSON_PAYLOAD) as mock_get_secret:
            first = get_client_secrets_path()
            second = get_client_secrets_path()
        assert first == second
        assert mock_get_secret.call_count == 1

    # ---- Case 3 ----
    def test_registers_exactly_one_atexit_handler_on_cache_miss(self):
        """Given キャッシュミス（初回呼び出し）
        When get_client_secrets_path() を呼ぶ
        Then atexit.register がちょうど 1 回呼ばれる
        """
        with (
            patch("youtube_automation.utils.secrets.atexit.register") as mock_register,
            patch("youtube_automation.utils.secrets.get_secret", return_value=_TEST_JSON_PAYLOAD),
        ):
            get_client_secrets_path()
        assert mock_register.call_count == 1

    # ---- Case 4 ----
    def test_creates_tempfile_with_owner_only_permissions(self):
        """Given get_secret がモック JSON を返す
        When get_client_secrets_path() を呼ぶ
        Then 作成された tempfile のパーミッションは 0o600
        """
        with patch("youtube_automation.utils.secrets.get_secret", return_value=_TEST_JSON_PAYLOAD):
            path = get_client_secrets_path()
        mode = os.stat(path).st_mode & 0o777
        assert mode == _EXPECTED_MODE

    # ---- Case 5 ----
    def test_tempfile_name_uses_expected_prefix_and_suffix(self):
        """Given get_secret がモック JSON を返す
        When get_client_secrets_path() を呼ぶ
        Then ファイル名は "client_secrets_" prefix / ".json" suffix
        """
        with patch("youtube_automation.utils.secrets.get_secret", return_value=_TEST_JSON_PAYLOAD):
            path = get_client_secrets_path()
        assert path.name.startswith(_EXPECTED_PREFIX)
        assert path.name.endswith(_EXPECTED_SUFFIX)

    # ---- Case 6 ----
    def test_does_not_register_atexit_on_cache_hit(self):
        """Given 1 回目で tempfile を作成済み
        When 2 回目の get_client_secrets_path() を呼ぶ
        Then atexit.register は再度呼ばれない（合計 1 回のまま）
        """
        with (
            patch("youtube_automation.utils.secrets.atexit.register") as mock_register,
            patch("youtube_automation.utils.secrets.get_secret", return_value=_TEST_JSON_PAYLOAD),
        ):
            get_client_secrets_path()
            get_client_secrets_path()
        assert mock_register.call_count == 1

    # ---- Case 7 ----
    def test_tempfile_content_matches_get_secret_return_value(self):
        """Given get_secret がモック JSON を返す
        When get_client_secrets_path() を呼ぶ
        Then 書き出された tempfile の中身は get_secret の戻り値と一致する
        """
        with patch("youtube_automation.utils.secrets.get_secret", return_value=_TEST_JSON_PAYLOAD):
            path = get_client_secrets_path()
        assert path.read_text() == _TEST_JSON_PAYLOAD

    # ---- Case 8 ----
    def test_registered_cleanup_handler_removes_tempfile(self):
        """Given get_client_secrets_path() で atexit に登録された cleanup
        When 登録された callback を手動実行する
        Then tempfile が削除される
        """
        with (
            patch("youtube_automation.utils.secrets.atexit.register") as mock_register,
            patch("youtube_automation.utils.secrets.get_secret", return_value=_TEST_JSON_PAYLOAD),
        ):
            path = get_client_secrets_path()
            cleanup = mock_register.call_args[0][0]
        assert path.exists()
        cleanup()
        assert not path.exists()

    # ---- Case 9 ----
    def test_cleanup_handler_is_idempotent_when_file_already_gone(self):
        """Given 登録された cleanup callback
        When ファイルを先に削除した状態で cleanup() を呼ぶ
        Then 例外は投げない（atexit 連鎖を止めない）
        """
        with (
            patch("youtube_automation.utils.secrets.atexit.register") as mock_register,
            patch("youtube_automation.utils.secrets.get_secret", return_value=_TEST_JSON_PAYLOAD),
        ):
            path = get_client_secrets_path()
            cleanup = mock_register.call_args[0][0]
        # 先に手動で消す
        path.unlink()
        assert not path.exists()
        # ここで例外が出れば pytest がテストを失敗にする
        cleanup()

    # ---- Case 10 ----
    def test_recreates_tempfile_when_cached_path_no_longer_exists(self):
        """Given キャッシュ変数に Path はあるが実ファイルが既に消えている状態
        When get_client_secrets_path() を呼ぶ
        Then 新しい tempfile が作成される
        """
        # キャッシュをセットしつつファイルは存在させない
        secrets_module._client_secrets_tempfile = Path("/tmp/__nonexistent_client_secrets__.json")
        with patch("youtube_automation.utils.secrets.get_secret", return_value=_TEST_JSON_PAYLOAD):
            path = get_client_secrets_path()
        assert path.exists()
        assert path != Path("/tmp/__nonexistent_client_secrets__.json")

    # ---- Case 11 ----
    def test_propagates_config_error_and_does_not_create_tempfile(self):
        """Given get_secret が ConfigError を raise する
        When get_client_secrets_path() を呼ぶ
        Then ConfigError が伝播し、tempfile は作成されない（mkstemp 未呼出）
        """
        with (
            patch(
                "youtube_automation.utils.secrets.get_secret",
                side_effect=ConfigError("test failure"),
            ),
            patch("youtube_automation.utils.secrets.tempfile.mkstemp") as mock_mkstemp,
        ):
            with pytest.raises(ConfigError, match="test failure"):
                get_client_secrets_path()
            mock_mkstemp.assert_not_called()
        # キャッシュも汚染されていない
        assert secrets_module._client_secrets_tempfile is None

    # ---- Case 12 ----
    def test_does_not_register_atexit_when_get_secret_raises(self):
        """Given get_secret が ConfigError を raise する
        When get_client_secrets_path() を呼ぶ
        Then atexit.register は呼ばれない（エラー時の atexit 汚染防止）
        """
        with (
            patch(
                "youtube_automation.utils.secrets.get_secret",
                side_effect=ConfigError("test failure"),
            ),
            patch("youtube_automation.utils.secrets.atexit.register") as mock_register,
        ):
            with pytest.raises(ConfigError):
                get_client_secrets_path()
        mock_register.assert_not_called()
