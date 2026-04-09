"""utils/secrets.py のユニットテスト。

検証する 3 経路:
1. os.environ に既にあれば op を呼ばずにそれを返す
2. os.environ に無く op がある場合は op read で取得し、os.environ にもセットする
3. どちらも失敗したら ConfigError を raise する
"""

from __future__ import annotations

import os
import subprocess
from unittest.mock import patch

import pytest

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.secrets import get_secret, reset_cache


@pytest.fixture(autouse=True)
def clean_env():
    """各テスト前後で GEMINI_API_KEY と lru_cache をクリーンにする"""
    saved = os.environ.pop("GEMINI_API_KEY", None)
    reset_cache()
    yield
    reset_cache()
    if saved is not None:
        os.environ["GEMINI_API_KEY"] = saved
    else:
        os.environ.pop("GEMINI_API_KEY", None)


class TestGetSecret:
    def test_returns_from_environ_when_present(self):
        """既に os.environ にあれば op を呼ばずにそれを返す"""
        os.environ["GEMINI_API_KEY"] = "from-env-12345"
        with patch("youtube_automation.utils.secrets.subprocess.run") as mock_run:
            value = get_secret("GEMINI_API_KEY")
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
            value = get_secret("GEMINI_API_KEY")
        assert value == "from-op-67890"
        mock_run.assert_called_once()

    def test_op_read_result_is_cached_in_environ(self):
        """op read で取得した値は os.environ にもセットされる"""
        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=["op", "read", "..."],
                returncode=0,
                stdout="cached-value\n",
                stderr="",
            )
            get_secret("GEMINI_API_KEY")
        assert os.environ.get("GEMINI_API_KEY") == "cached-value"

    def test_raises_config_error_when_op_unavailable_and_environ_empty(self):
        """op が無く os.environ も空なら ConfigError"""
        with patch("youtube_automation.utils.secrets.shutil.which", return_value=None):
            with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
                get_secret("GEMINI_API_KEY")

    def test_raises_config_error_when_op_read_fails(self):
        """op はあるが op read が失敗したら ConfigError"""
        with (
            patch("youtube_automation.utils.secrets.shutil.which", return_value="/usr/bin/op"),
            patch("youtube_automation.utils.secrets.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1, cmd=["op", "read", "..."]
            )
            with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
                get_secret("GEMINI_API_KEY")

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
            get_secret("GEMINI_API_KEY")
            get_secret("GEMINI_API_KEY")
        mock_run.assert_called_once()
