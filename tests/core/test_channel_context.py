"""`core.channel_context` のチャンネルルート解決テスト (#5206)."""

from __future__ import annotations

import pytest

from youtube_automation.core import channel_context
from youtube_automation.core.errors import ConfigError


@pytest.fixture(autouse=True)
def _fresh_channel_context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CHANNEL_DIR", raising=False)
    channel_context.reset_channel_context()
    yield
    channel_context.reset_channel_context()


def test_channel_dir_env_var_wins(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("CHANNEL_DIR", str(tmp_path))
    assert channel_context.channel_dir() == tmp_path


def test_channel_dir_finds_config_channel_ancestor(monkeypatch: pytest.MonkeyPatch, tmp_path):
    (tmp_path / "config" / "channel").mkdir(parents=True)
    nested = tmp_path / "collections" / "foo"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert channel_context.channel_dir() == tmp_path


@pytest.mark.parametrize("marker", ["collections", "auth", "branding"])
def test_channel_dir_falls_back_to_channel_root_marker(monkeypatch: pytest.MonkeyPatch, tmp_path, marker):
    """config/channel/ がない開設直後チャンネルはルート目印で解決する (#5206)."""
    (tmp_path / marker).mkdir()
    monkeypatch.chdir(tmp_path)
    assert channel_context.channel_dir() == tmp_path


def test_channel_dir_marker_resolves_from_nested_dir(monkeypatch: pytest.MonkeyPatch, tmp_path):
    (tmp_path / "collections" / "foo").mkdir(parents=True)
    monkeypatch.chdir(tmp_path / "collections" / "foo")
    assert channel_context.channel_dir() == tmp_path


def test_channel_dir_config_channel_wins_over_marker(monkeypatch: pytest.MonkeyPatch, tmp_path):
    channel_root = tmp_path / "channel"
    (channel_root / "config" / "channel").mkdir(parents=True)
    (channel_root / "collections").mkdir()
    monkeypatch.chdir(channel_root / "collections")
    assert channel_context.channel_dir() == channel_root


def test_channel_dir_raises_without_markers(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="CHANNEL_DIR 環境変数"):
        channel_context.channel_dir()
