"""Channel target resolution precedence and rejection contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from youtube_automation.configuration.channel_target import resolve_existing_target_dir
from youtube_automation.core.errors import ConfigError


def test_explicit_target_precedes_channel_dir_and_cwd(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit"
    configured = tmp_path / "configured"
    cwd = tmp_path / "cwd"
    explicit.mkdir()
    configured.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("CHANNEL_DIR", str(configured))
    monkeypatch.setattr(Path, "cwd", lambda: cwd)

    assert resolve_existing_target_dir(str(explicit)) == explicit.resolve()


def test_channel_dir_precedes_cwd(tmp_path, monkeypatch):
    configured = tmp_path / "configured"
    cwd = tmp_path / "cwd"
    configured.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("CHANNEL_DIR", str(configured))
    monkeypatch.setattr(Path, "cwd", lambda: cwd)

    assert resolve_existing_target_dir(None) == configured.resolve()


def test_cwd_is_fallback_when_channel_dir_is_unset(tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.delenv("CHANNEL_DIR", raising=False)
    monkeypatch.setattr(Path, "cwd", lambda: cwd)

    assert resolve_existing_target_dir(None) == cwd.resolve()


@pytest.mark.parametrize("source", ["explicit", "environment"])
@pytest.mark.parametrize("target_kind", ["missing", "file"])
def test_configured_target_rejects_missing_and_non_directory(
    tmp_path,
    monkeypatch,
    source,
    target_kind,
):
    target = tmp_path / "target"
    if target_kind == "file":
        target.write_text("not a directory", encoding="utf-8")
    monkeypatch.delenv("CHANNEL_DIR", raising=False)

    if source == "explicit":
        explicit_target = str(target)
        message = "--target"
    else:
        monkeypatch.setenv("CHANNEL_DIR", str(target))
        explicit_target = None
        message = "CHANNEL_DIR"

    with pytest.raises(ConfigError, match=message):
        resolve_existing_target_dir(explicit_target)


def test_invalid_cwd_fallback_is_rejected(tmp_path, monkeypatch):
    invalid_cwd = tmp_path / "not-a-directory"
    invalid_cwd.write_text("file", encoding="utf-8")
    monkeypatch.delenv("CHANNEL_DIR", raising=False)
    monkeypatch.setattr(Path, "cwd", lambda: invalid_cwd)

    with pytest.raises(ConfigError, match="作業ディレクトリ"):
        resolve_existing_target_dir(None)
