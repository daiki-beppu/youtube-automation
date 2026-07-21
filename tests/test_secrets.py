"""utils/secrets.py のユニットテスト。

検証する 3 経路:
1. os.environ に既にあれば op を呼ばずにそれを返す
2. os.environ に無く、`YOUTUBE_AUTOMATION_DISABLE_OP_READ=1` でなく、op がある場合は
   op read で取得して返す（os.environ への書き戻しは行わない）
3. どちらも失敗したら ConfigError を raise する

通常テストでは `tests/conftest.py` が `YOUTUBE_AUTOMATION_DISABLE_OP_READ=1` を
既定有効にし、op discovery/spawn を行わず最終エラーへ進む。op fallback を検証する
テストだけ明示的に解除する。
"""

from __future__ import annotations

import os
import subprocess
from unittest.mock import patch

import pytest

from youtube_automation.utils import secrets as secrets_module
from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.secrets import (
    _SECRET_REFS,
    get_client_secrets_config,
    get_secret,
    reset_cache,
)

_TEST_SECRET = "CLIENT_SECRETS_JSON"
_MANAGED_SECRETS = ("CLIENT_SECRETS_JSON", "OPENAI_API_KEY", "GEMINI_API_KEY")
_OP_READ_DISABLED_ENV = secrets_module._OP_READ_DISABLED_ENV


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
            patch.dict(os.environ, {_OP_READ_DISABLED_ENV: "0"}),
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
        mock_run.assert_called_once_with(
            ["op", "read", _SECRET_REFS[_TEST_SECRET]],
            check=True,
            capture_output=True,
            text=True,
            timeout=secrets_module._OP_READ_TIMEOUT_SEC,
        )

    def test_op_read_result_is_not_written_to_environ(self):
        """op read で取得した値は os.environ にセットされない（global env 注入禁止: Issue #163）"""
        with (
            patch.dict(os.environ, {_OP_READ_DISABLED_ENV: "0"}),
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
        with (
            patch.dict(os.environ, {_OP_READ_DISABLED_ENV: "0"}),
            patch("youtube_automation.utils.secrets.shutil.which", return_value=None),
        ):
            with pytest.raises(ConfigError, match=_TEST_SECRET):
                get_secret(_TEST_SECRET)

    def test_test_harness_disables_op_read_even_when_op_is_on_path(self):
        """通常テストでは op が PATH 上にあっても実 op read 分岐へ入らない。"""
        with (
            patch.dict(os.environ, {_OP_READ_DISABLED_ENV: "1"}),
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op") as mock_which,
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            with pytest.raises(ConfigError, match=_TEST_SECRET):
                get_secret(_TEST_SECRET)
        mock_which.assert_not_called()
        mock_run.assert_not_called()

    def test_raises_config_error_when_op_read_fails(self):
        """op はあるが op read が失敗したら ConfigError"""
        with (
            patch.dict(os.environ, {_OP_READ_DISABLED_ENV: "0"}),
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
            patch.dict(os.environ, {_OP_READ_DISABLED_ENV: "0"}),
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
            patch.dict(os.environ, {_OP_READ_DISABLED_ENV: "0"}),
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
        with (
            patch.dict(os.environ, {_OP_READ_DISABLED_ENV: "0"}),
            patch("youtube_automation.utils.secrets.shutil.which", return_value=None),
        ):
            with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
                get_secret("OPENAI_API_KEY")


class TestGeminiApiKeyRegistered:
    def test_gemini_api_key_uses_expected_op_reference(self):
        assert _SECRET_REFS["GEMINI_API_KEY"] == "op://Personal/Gemini_API_Key/credential"

    def test_gemini_api_key_returns_from_environ(self):
        os.environ["GEMINI_API_KEY"] = "gemini-from-env"
        assert get_secret("GEMINI_API_KEY") == "gemini-from-env"

    def test_gemini_api_key_fails_loud_when_unavailable(self):
        with patch.dict(os.environ, {_OP_READ_DISABLED_ENV: "1"}):
            with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
                get_secret("GEMINI_API_KEY")


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
            patch.dict(os.environ, {_OP_READ_DISABLED_ENV: "0"}),
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
        with (
            patch.dict(os.environ, {_OP_READ_DISABLED_ENV: "0"}),
            patch("youtube_automation.utils.secrets.shutil.which", return_value=None),
        ):
            with pytest.raises(ConfigError, match=name):
                get_secret(name)


class TestGetClientSecretsConfig:
    """client_secrets JSON をディスクへ書かずに解決する契約。"""

    def test_returns_parsed_json_object(self):
        with patch("youtube_automation.utils.secrets.get_secret", return_value='{"installed": {}}'):
            assert get_client_secrets_config() == {"installed": {}}

    def test_rejects_invalid_json_without_exposing_secret(self):
        raw = "not-json-secret-value"
        with patch("youtube_automation.utils.secrets.get_secret", return_value=raw):
            with pytest.raises(ConfigError) as exc_info:
                get_client_secrets_config()
        assert "JSON として解釈できません" in str(exc_info.value)
        assert raw not in str(exc_info.value)

    @pytest.mark.parametrize("raw", ["[]", '"text"', "null"])
    def test_rejects_non_object_json(self, raw: str):
        with patch("youtube_automation.utils.secrets.get_secret", return_value=raw):
            with pytest.raises(ConfigError, match="JSON object"):
                get_client_secrets_config()
