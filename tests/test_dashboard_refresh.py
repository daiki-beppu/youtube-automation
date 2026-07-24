from __future__ import annotations

from pathlib import Path

from youtube_automation.infrastructure.errors import ConfigError
from youtube_automation.utils.dashboard_refresh import refresh_dashboard_channels


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
