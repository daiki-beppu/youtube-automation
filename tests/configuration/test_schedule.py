import json
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from youtube_automation.configuration.loader import load_schedule_config, load_schedule_config_from_file


@pytest.mark.parametrize(
    ("schedule", "enabled"),
    [
        ({"auto_schedule_enabled": True}, True),
        ({"auto_schedule_enabled": False, "cadence": ["mon"], "publish_time": "20:00"}, False),
        ({"cadence": ["mon"]}, True),
        ({"cadence": []}, False),
        ({"publish_time": "20:00"}, True),
        ({"publish_time": ""}, False),
        ({"day1_time": "20:00"}, False),
        ({}, False),
    ],
)
def test_scheduling_enabled_priority(tmp_path: Path, schedule: dict[str, object], enabled: bool) -> None:
    _write_schedule(tmp_path, {"schedule": schedule})

    assert load_schedule_config(tmp_path).scheduling_enabled is enabled


def test_resolves_schedule_fields_and_defaults(tmp_path: Path) -> None:
    _write_schedule(
        tmp_path,
        {
            "schedule": {"timezone": "America/New_York", "day1_time": "21:30", "cadence": ["mon", "fri"]},
            "upload_settings": {"category_id": "22", "auto_create_playlist": False, "max_retries": 7},
            "collections_management": {"auto_move_to_live": False},
            "api_limits": {"upload_quota_per_day": 3, "concurrent_uploads": 2},
        },
    )

    config = load_schedule_config(tmp_path)

    assert config.timezone == ZoneInfo("America/New_York")
    assert config.publish_time == "21:30"
    assert config.cadence == ("mon", "fri")
    assert config.category_id == "22"
    assert config.auto_create_playlist is False
    assert config.max_retries == 7
    assert config.retry_delay_seconds == 300
    assert config.auto_move_to_live is False
    assert config.upload_quota_per_day == 3
    assert config.concurrent_uploads == 2


def test_missing_file_uses_explicit_defaults(tmp_path: Path) -> None:
    config = load_schedule_config(tmp_path)

    assert config.timezone == ZoneInfo("Asia/Tokyo")
    assert config.publish_time == "10:00"
    assert config.cadence == ()
    assert config.scheduling_enabled is False
    assert config.auto_move_to_live is True
    assert config.upload_quota_per_day == 6


def test_from_file_reads_a_path_outside_a_config_directory(tmp_path: Path) -> None:
    path = tmp_path / "backup" / "my_schedule.json"
    path.parent.mkdir()
    payload = {"schedule": {"auto_schedule_enabled": True, "publish_time": "21:00"}}
    path.write_text(json.dumps(payload), encoding="utf-8")

    config = load_schedule_config_from_file(path)

    assert config.scheduling_enabled is True
    assert config.publish_time == "21:00"


def test_from_file_uses_defaults_when_the_file_is_missing(tmp_path: Path) -> None:
    config = load_schedule_config_from_file(tmp_path / "absent.json")

    assert config.publish_time == "10:00"
    assert config.scheduling_enabled is False


def test_scheduling_explicitly_disabled_tracks_the_auto_schedule_flag(tmp_path: Path) -> None:
    _write_schedule(tmp_path, {"schedule": {"auto_schedule_enabled": False}})

    assert load_schedule_config(tmp_path).scheduling_explicitly_disabled is True
    assert load_schedule_config_from_file(tmp_path / "absent.json").scheduling_explicitly_disabled is False


def test_warns_that_upload_privacy_status_is_ignored(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _write_schedule(tmp_path, {"upload_settings": {"privacy_status": "public"}})

    with caplog.at_level(logging.WARNING):
        load_schedule_config(tmp_path)

    assert "youtube.json" in caplog.text
    assert "privacy_status" in caplog.text


def _write_schedule(channel_dir: Path, value: dict[str, object]) -> None:
    config_dir = channel_dir / "config"
    config_dir.mkdir()
    (config_dir / "schedule_config.json").write_text(json.dumps(value), encoding="utf-8")
