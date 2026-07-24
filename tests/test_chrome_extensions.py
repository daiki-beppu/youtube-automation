"""Chrome unpacked extension detection tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_automation.infrastructure.errors import ConfigError
from youtube_automation.utils.chrome_extensions import resolve_unpacked_extension_origin


def _write_preferences(profile_dir: Path, filename: str, settings: dict[str, object]) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    payload = {"extensions": {"settings": settings}}
    (profile_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


def _write_preferences_payload(profile_dir: Path, filename: str, payload: object) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


def _extension_path(tmp_path: Path, name: str) -> str:
    return str(tmp_path / "chrome-extensions" / name)


def test_resolve_unpacked_extension_origin_matches_secure_preferences(tmp_path):
    _write_preferences(
        tmp_path / "Default",
        "Secure Preferences",
        {
            "gdjhjiphejeeclngbljhajiffhpdepee": {"path": _extension_path(tmp_path, "suno-helper")},
            "ignoredrelativeextensionid": {"path": "relative/suno-helper"},
            "ignoredotherbasename": {"path": _extension_path(tmp_path, "other-helper")},
        },
    )

    resolved = resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    assert resolved.name == "suno-helper"
    assert resolved.extension_id == "gdjhjiphejeeclngbljhajiffhpdepee"
    assert resolved.origin == "chrome-extension://gdjhjiphejeeclngbljhajiffhpdepee"
    assert resolved.profile == "Default"
    assert resolved.path == Path(_extension_path(tmp_path, "suno-helper"))


def test_resolve_unpacked_extension_origin_uses_preferences_fallback(tmp_path):
    _write_preferences(
        tmp_path / "Profile 1",
        "Preferences",
        {"abcdefghijklmnopabcdefghijklmnop": {"path": _extension_path(tmp_path, "distrokid-helper")}},
    )

    resolved = resolve_unpacked_extension_origin("distrokid-helper", chrome_user_data_dir=tmp_path)

    assert resolved.origin == "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    assert resolved.profile == "Profile 1"


def test_resolve_unpacked_extension_origin_prefers_secure_preferences_when_both_exist(tmp_path):
    profile_dir = tmp_path / "Default"
    _write_preferences(
        profile_dir,
        "Preferences",
        {"abcdefghijklmnopabcdefghijklmnop": {"path": _extension_path(tmp_path, "suno-helper")}},
    )
    _write_preferences(
        profile_dir,
        "Secure Preferences",
        {"gdjhjiphejeeclngbljhajiffhpdepee": {"path": _extension_path(tmp_path, "suno-helper")}},
    )

    resolved = resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    assert resolved.extension_id == "gdjhjiphejeeclngbljhajiffhpdepee"
    assert resolved.origin == "chrome-extension://gdjhjiphejeeclngbljhajiffhpdepee"


def test_resolve_unpacked_extension_origin_missing_extension_guides_allow_origin(tmp_path):
    _write_preferences(
        tmp_path / "Default",
        "Secure Preferences",
        {"abcdefghijklmnopabcdefghijklmnop": {"path": _extension_path(tmp_path, "other-helper")}},
    )

    with pytest.raises(ConfigError) as exc_info:
        resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    message = str(exc_info.value)
    assert "suno-helper" in message
    assert "--allow-origin chrome-extension://<EXTENSION_ID>" in message


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"extensions": None},
        {"extensions": {"settings": []}},
        {"extensions": {"settings": {"gdjhjiphejeeclngbljhajiffhpdepee": None}}},
        {"extensions": {"settings": {"gdjhjiphejeeclngbljhajiffhpdepee": {"path": None}}}},
        {"extensions": {"settings": {"gdjhjiphejeeclngbljhajiffhpdepee": {"path": "relative/suno-helper"}}}},
    ),
)
def test_resolve_unpacked_extension_origin_ignores_valid_but_malformed_preferences_shape(
    tmp_path,
    payload,
):
    _write_preferences_payload(tmp_path / "Default", "Secure Preferences", payload)

    with pytest.raises(ConfigError) as exc_info:
        resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    message = str(exc_info.value)
    assert "suno-helper" in message
    assert "was not found" in message
    assert "--allow-origin chrome-extension://<EXTENSION_ID>" in message


def test_resolve_unpacked_extension_origin_accepts_same_id_across_profiles(tmp_path):
    extension_id = "gdjhjiphejeeclngbljhajiffhpdepee"
    _write_preferences(
        tmp_path / "Default",
        "Secure Preferences",
        {extension_id: {"path": _extension_path(tmp_path, "suno-helper")}},
    )
    _write_preferences(
        tmp_path / "Profile 1",
        "Secure Preferences",
        {extension_id: {"path": _extension_path(tmp_path, "suno-helper")}},
    )

    resolved = resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    assert resolved.extension_id == extension_id
    assert resolved.origin == f"chrome-extension://{extension_id}"


def test_resolve_unpacked_extension_origin_conflicting_ids_lists_candidates(tmp_path):
    _write_preferences(
        tmp_path / "Default",
        "Secure Preferences",
        {"gdjhjiphejeeclngbljhajiffhpdepee": {"path": _extension_path(tmp_path, "suno-helper")}},
    )
    _write_preferences(
        tmp_path / "Profile 1",
        "Secure Preferences",
        {"abcdefghijklmnopabcdefghijklmnop": {"path": _extension_path(tmp_path, "suno-helper")}},
    )

    with pytest.raises(ConfigError) as exc_info:
        resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    message = str(exc_info.value)
    assert "matched multiple extension IDs" in message
    assert "Default: gdjhjiphejeeclngbljhajiffhpdepee" in message
    assert "Profile 1: abcdefghijklmnopabcdefghijklmnop" in message
    assert "--allow-origin chrome-extension://<EXTENSION_ID>" in message


def test_resolve_unpacked_extension_origin_parse_failure_guides_allow_origin(tmp_path):
    profile_dir = tmp_path / "Default"
    profile_dir.mkdir()
    (profile_dir / "Secure Preferences").write_text("{", encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    message = str(exc_info.value)
    assert "Failed to parse Chrome preferences" in message
    assert "--allow-origin chrome-extension://<EXTENSION_ID>" in message


def test_resolve_unpacked_extension_origin_read_failure_guides_allow_origin(tmp_path, monkeypatch):
    profile_dir = tmp_path / "Default"
    profile_dir.mkdir()
    preferences_path = profile_dir / "Secure Preferences"
    preferences_path.write_text("{}", encoding="utf-8")

    def fail_read_text(self, *args, **kwargs):
        if self == preferences_path:
            raise OSError("permission denied")
        return original_read_text(self, *args, **kwargs)

    original_read_text = Path.read_text
    monkeypatch.setattr(Path, "read_text", fail_read_text)

    with pytest.raises(ConfigError) as exc_info:
        resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    message = str(exc_info.value)
    assert "Failed to read Chrome preferences" in message
    assert str(preferences_path) in message
    assert "permission denied" in message
    assert "--allow-origin chrome-extension://<EXTENSION_ID>" in message


def test_resolve_unpacked_extension_origin_profile_scan_failure_guides_allow_origin(tmp_path, monkeypatch):
    tmp_path.mkdir(exist_ok=True)

    def fail_iterdir(self):
        if self == tmp_path:
            raise OSError("permission denied")
        return original_iterdir(self)

    original_iterdir = Path.iterdir
    monkeypatch.setattr(Path, "iterdir", fail_iterdir)

    with pytest.raises(ConfigError) as exc_info:
        resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    message = str(exc_info.value)
    assert "Failed to scan Chrome profiles" in message
    assert str(tmp_path) in message
    assert "permission denied" in message
    assert "--allow-origin chrome-extension://<EXTENSION_ID>" in message
