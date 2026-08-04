from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from youtube_automation import configuration
from youtube_automation.core.errors import AutomationError, ConfigError
from youtube_automation.infrastructure.analytics.dashboard_refresh import (
    collect_channel_analytics,
    refresh_dashboard_channels,
)


def test_refresh_attempts_every_channel_and_isolates_expected_failure(tmp_path: Path) -> None:
    first = tmp_path / "first"
    broken = tmp_path / "broken"
    last = tmp_path / "last"
    attempted: list[Path] = []

    def collect(channel: Path) -> None:
        attempted.append(channel)
        if channel == broken:
            raise ConfigError("readonly token is missing")

    errors = refresh_dashboard_channels([first, broken, last], collect_channel=collect)

    assert attempted == [first, broken, last]
    assert errors == {broken: "readonly token is missing"}


def test_refresh_isolates_unexpected_runtime_failure(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    last = tmp_path / "last"
    attempted: list[Path] = []

    def collect(channel: Path) -> None:
        attempted.append(channel)
        if channel == broken:
            raise RuntimeError("network adapter failed")

    errors = refresh_dashboard_channels([broken, last], collect_channel=collect)

    assert attempted == [broken, last]
    assert errors == {broken: "network adapter failed"}


@pytest.mark.parametrize(
    ("initial_dir", "initial_slug"),
    [(None, None), ("/previous/channel", "previous-slug")],
)
def test_collect_channel_restores_environment_and_configuration_after_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    initial_dir: str | None,
    initial_slug: str | None,
) -> None:
    channel = tmp_path / "selected"
    if initial_dir is None:
        monkeypatch.delenv("CHANNEL_DIR", raising=False)
    else:
        monkeypatch.setenv("CHANNEL_DIR", initial_dir)
    if initial_slug is None:
        monkeypatch.delenv("CHANNEL", raising=False)
    else:
        monkeypatch.setenv("CHANNEL", initial_slug)
    reset = Mock(wraps=configuration.reset)
    monkeypatch.setattr(configuration, "reset", reset)
    system = Mock()

    def run_data_collection(*, days: int, depth: str) -> dict[str, bool]:
        assert days == 30
        assert depth == "standard"
        assert os.environ["CHANNEL_DIR"] == str(channel)
        assert "CHANNEL" not in os.environ
        return {"success": True}

    system.run_data_collection.side_effect = run_data_collection
    factory = Mock(return_value=system)

    collect_channel_analytics(channel, factory)

    assert reset.call_count == 2
    assert factory.call_count == 1
    system.run_data_collection.assert_called_once_with(days=30, depth="standard")
    assert os.environ.get("CHANNEL_DIR") == initial_dir
    assert os.environ.get("CHANNEL") == initial_slug


def test_collect_channel_restores_environment_and_raises_automation_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("CHANNEL_DIR", "/previous/channel")
    monkeypatch.setenv("CHANNEL", "previous-slug")
    reset = Mock(wraps=configuration.reset)
    monkeypatch.setattr(configuration, "reset", reset)
    system = Mock()

    def run_data_collection(*, days: int, depth: str) -> dict[str, object]:
        assert days == 30
        assert depth == "standard"
        assert os.environ["CHANNEL_DIR"] == str(tmp_path / "selected")
        assert "CHANNEL" not in os.environ
        return {
            "success": False,
            "error": "reporting collection failed",
        }

    system.run_data_collection.side_effect = run_data_collection

    with pytest.raises(AutomationError, match="reporting collection failed"):
        collect_channel_analytics(tmp_path / "selected", Mock(return_value=system))

    assert reset.call_count == 2
    assert os.environ["CHANNEL_DIR"] == "/previous/channel"
    assert os.environ["CHANNEL"] == "previous-slug"
