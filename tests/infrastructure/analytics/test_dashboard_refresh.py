from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from youtube_automation import configuration
from youtube_automation.core.errors import AutomationError, ConfigError, YouTubeAPIError
from youtube_automation.infrastructure.analytics import dashboard_refresh
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
    monkeypatch.setattr(
        configuration,
        "load_config",
        Mock(
            return_value=SimpleNamespace(youtube=SimpleNamespace(api=SimpleNamespace(default_publish_timezone="UTC")))
        ),
    )
    system = Mock()
    system.collector.get_all_channel_videos.return_value = []

    def run_data_collection(*, days: int, depth: str) -> dict[str, bool]:
        assert days == 30
        assert depth == "standard"
        assert os.environ["CHANNEL_DIR"] == str(channel)
        assert "CHANNEL" not in os.environ
        (channel / "data").mkdir(parents=True)
        return {"success": True}

    system.run_data_collection.side_effect = run_data_collection
    factory = Mock(return_value=system)

    collect_channel_analytics(channel, factory)

    assert reset.call_count == 2
    assert factory.call_count == 1
    system.run_data_collection.assert_called_once_with(days=30, depth="standard")
    system.collector.get_all_channel_videos.assert_called_once_with()
    assert (channel / "data" / "dashboard_publications.json").is_file()
    assert os.environ.get("CHANNEL_DIR") == initial_dir
    assert os.environ.get("CHANNEL") == initial_slug


@pytest.mark.parametrize(
    "cache_contents",
    [
        None,
        json.dumps(
            {
                "schema_version": 1,
                "fetched_at": "2026-08-07T11:59:59+00:00",
                "timezone": "UTC",
                "days": {},
            }
        ),
        "{not-json",
    ],
    ids=["missing", "stale", "corrupt"],
)
def test_collect_channel_should_refresh_publication_cache_when_cache_is_unusable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cache_contents: str | None,
) -> None:
    channel = tmp_path / "selected"
    fixed_now = datetime(2026, 8, 8, 12, tzinfo=UTC)
    if cache_contents is not None:
        (channel / "data").mkdir(parents=True, exist_ok=True)
        (channel / "data" / "dashboard_publications.json").write_text(cache_contents, encoding="utf-8")

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(dashboard_refresh, "datetime", FixedDateTime)
    monkeypatch.setattr(
        configuration,
        "load_config",
        Mock(
            return_value=SimpleNamespace(
                youtube=SimpleNamespace(api=SimpleNamespace(default_publish_timezone="America/Los_Angeles"))
            )
        ),
    )
    collector = Mock()
    collector.get_all_channel_videos.return_value = [
        {"published_at": "2026-08-08T01:00:00Z"},
        {"published_at": "2026-08-08T10:00:00Z"},
    ]
    system = Mock(collector=collector)

    def run_data_collection(*, days: int, depth: str) -> dict[str, bool]:
        assert (days, depth) == (30, "standard")
        collector.get_all_channel_videos()
        (channel / "data").mkdir(parents=True, exist_ok=True)
        return {"success": True}

    system.run_data_collection.side_effect = run_data_collection
    factory = Mock(return_value=system)

    collect_channel_analytics(channel, factory)

    factory.assert_called_once_with()
    assert collector.get_all_channel_videos.call_count == 2
    payload = json.loads((channel / "data" / "dashboard_publications.json").read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": 1,
        "fetched_at": "2026-08-08T12:00:00+00:00",
        "timezone": "America/Los_Angeles",
        "days": {"2026-08-07": 1, "2026-08-08": 1},
    }


def test_collect_channel_should_reuse_publication_cache_when_cache_is_fresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    channel = tmp_path / "selected"
    fixed_now = datetime(2026, 8, 8, 12, tzinfo=UTC)
    publication_path = channel / "data" / "dashboard_publications.json"
    cached_payload = {
        "schema_version": 1,
        "fetched_at": "2026-08-08T12:00:00+00:00",
        "timezone": "Asia/Tokyo",
        "days": {"2026-08-08": 2},
    }
    publication_path.parent.mkdir(parents=True)
    publication_path.write_text(json.dumps(cached_payload), encoding="utf-8")

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(dashboard_refresh, "datetime", FixedDateTime)
    monkeypatch.setattr(
        configuration,
        "load_config",
        Mock(
            return_value=SimpleNamespace(youtube=SimpleNamespace(api=SimpleNamespace(default_publish_timezone="UTC")))
        ),
    )
    collector = Mock()
    collector.get_all_channel_videos.return_value = []
    system = Mock(collector=collector)

    def run_data_collection(*, days: int, depth: str) -> dict[str, bool]:
        assert (days, depth) == (30, "standard")
        collector.get_all_channel_videos()
        return {"success": True}

    system.run_data_collection.side_effect = run_data_collection

    collect_channel_analytics(channel, Mock(return_value=system))

    system.run_data_collection.assert_called_once_with(days=30, depth="standard")
    collector.get_all_channel_videos.assert_called_once_with()
    assert json.loads(publication_path.read_text(encoding="utf-8")) == cached_payload


def test_collect_channel_should_refresh_fresh_publication_cache_when_forced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    channel = tmp_path / "selected"
    fixed_now = datetime(2026, 8, 8, 12, tzinfo=UTC)
    publication_path = channel / "data" / "dashboard_publications.json"
    publication_path.parent.mkdir(parents=True)
    publication_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "fetched_at": "2026-08-08T11:00:00+00:00",
                "timezone": "UTC",
                "days": {"2026-08-07": 1},
            }
        ),
        encoding="utf-8",
    )

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(dashboard_refresh, "datetime", FixedDateTime)
    monkeypatch.setattr(
        configuration,
        "load_config",
        Mock(
            return_value=SimpleNamespace(youtube=SimpleNamespace(api=SimpleNamespace(default_publish_timezone="UTC")))
        ),
    )
    collector = Mock()
    collector.get_all_channel_videos.side_effect = [
        [],
        [{"published_at": "2026-08-08T01:00:00Z"}],
    ]
    system = Mock(collector=collector)

    def run_data_collection(*, days: int, depth: str) -> dict[str, bool]:
        assert (days, depth) == (30, "standard")
        collector.get_all_channel_videos()
        return {"success": True}

    system.run_data_collection.side_effect = run_data_collection

    collect_channel_analytics(channel, Mock(return_value=system), force_publication_refresh=True)

    assert collector.get_all_channel_videos.call_count == 2
    assert json.loads(publication_path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "fetched_at": "2026-08-08T12:00:00+00:00",
        "timezone": "UTC",
        "days": {"2026-08-08": 1},
    }


def test_refresh_channels_should_keep_stale_cache_and_continue_when_publication_refresh_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    broken = tmp_path / "broken"
    last = tmp_path / "last"
    fixed_now = datetime(2026, 8, 8, 12, tzinfo=UTC)
    publication_path = broken / "data" / "dashboard_publications.json"
    cached_payload = {
        "schema_version": 1,
        "fetched_at": "2026-08-07T11:59:59+00:00",
        "timezone": "Asia/Tokyo",
        "days": {"2026-08-07": 2},
    }
    publication_path.parent.mkdir(parents=True)
    publication_path.write_text(json.dumps(cached_payload), encoding="utf-8")

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(dashboard_refresh, "datetime", FixedDateTime)
    monkeypatch.setattr(
        configuration,
        "load_config",
        Mock(
            return_value=SimpleNamespace(youtube=SimpleNamespace(api=SimpleNamespace(default_publish_timezone="UTC")))
        ),
    )
    collector = Mock()
    collector.get_all_channel_videos.side_effect = [[], YouTubeAPIError("uploads playlist request failed")]
    system = Mock(collector=collector)

    def run_data_collection(*, days: int, depth: str) -> dict[str, bool]:
        assert (days, depth) == (30, "standard")
        collector.get_all_channel_videos()
        return {"success": True}

    system.run_data_collection.side_effect = run_data_collection
    attempted: list[Path] = []

    def collect(channel: Path) -> None:
        attempted.append(channel)
        if channel == broken:
            collect_channel_analytics(channel, Mock(return_value=system))

    errors = refresh_dashboard_channels([broken, last], collect_channel=collect)

    assert attempted == [broken, last]
    assert errors == {}
    assert json.loads(publication_path.read_text(encoding="utf-8")) == {
        **cached_payload,
        "error": {
            "code": "publication_refresh_failed",
            "message": "uploads playlist request failed",
            "attempted_at": "2026-08-08T12:00:00+00:00",
        },
    }


def test_collect_channel_should_raise_publication_error_when_valid_cache_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    channel = tmp_path / "selected"
    monkeypatch.setattr(
        configuration,
        "load_config",
        Mock(
            return_value=SimpleNamespace(youtube=SimpleNamespace(api=SimpleNamespace(default_publish_timezone="UTC")))
        ),
    )
    collector = Mock()
    collector.get_all_channel_videos.side_effect = [[], YouTubeAPIError("uploads playlist request failed")]
    system = Mock(collector=collector)

    def run_data_collection(*, days: int, depth: str) -> dict[str, bool]:
        assert (days, depth) == (30, "standard")
        collector.get_all_channel_videos()
        return {"success": True}

    system.run_data_collection.side_effect = run_data_collection

    with pytest.raises(YouTubeAPIError, match="uploads playlist request failed"):
        collect_channel_analytics(channel, Mock(return_value=system))

    assert not (channel / "data" / "dashboard_publications.json").exists()


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
    system.collector.get_all_channel_videos.assert_not_called()
    assert not (tmp_path / "selected" / "data" / "dashboard_publications.json").exists()
    assert os.environ["CHANNEL_DIR"] == "/previous/channel"
    assert os.environ["CHANNEL"] == "previous-slug"
