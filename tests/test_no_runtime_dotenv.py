"""チャンネルルート dotenv を production runtime へ再導入させない contract test."""

import os
from pathlib import Path

import pytest

from youtube_automation.core.errors import ConfigError
from youtube_automation.infrastructure.secrets import get_secret, reset_cache

_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_secret_resolution_ignores_channel_dotenv(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=dotenv-only-secret\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("YOUTUBE_AUTOMATION_DISABLE_OP_READ", "1")
    reset_cache()

    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        get_secret("OPENAI_API_KEY")
    assert "OPENAI_API_KEY" not in os.environ


def test_python_dotenv_is_not_a_package_dependency() -> None:
    assert "python-dotenv" not in (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "python-dotenv"' not in (_ROOT / "uv.lock").read_text(encoding="utf-8")
