"""Chrome unpacked extension detection tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import youtube_automation.infrastructure.collections.chrome_extensions as chrome_extensions
from youtube_automation.core.errors import ConfigError
from youtube_automation.infrastructure.collections.chrome_extensions import resolve_unpacked_extension_origin


def _write_preferences(profile_dir: Path, filename: str, settings: dict[str, object]) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    payload = {"extensions": {"settings": settings}}
    (profile_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


def _write_preferences_payload(profile_dir: Path, filename: str, payload: object) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


def _extension_path(tmp_path: Path, name: str) -> str:
    return str(tmp_path / "chrome-extensions" / name)


def test_resolve_unpacked_extension_origin_rejects_empty_name_with_manual_fallback() -> None:
    with pytest.raises(ConfigError) as exc_info:
        resolve_unpacked_extension_origin("")

    message = str(exc_info.value)
    assert "must not be empty" in message
    assert "--allow-origin" in message


def test_resolve_unpacked_extension_origin_uses_default_chrome_user_data_root(tmp_path, monkeypatch):
    extension_id = "gdjhjiphejeeclngbljhajiffhpdepee"
    default_root = tmp_path / "Library" / "Application Support" / "Google" / "Chrome"
    _write_preferences(
        default_root / "Default",
        "Secure Preferences",
        {extension_id: {"path": _extension_path(tmp_path, "suno-helper")}},
    )
    monkeypatch.setattr(chrome_extensions.Path, "home", lambda: tmp_path)

    resolved = resolve_unpacked_extension_origin("suno-helper")

    assert resolved.extension_id == extension_id
    assert resolved.profile == "Default"


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


@pytest.mark.parametrize(
    "folder_name",
    (
        "suno-helper-0.2.5",
        "suno-helper-0.2.5-chrome",
        "suno-helper-chrome",
    ),
)
def test_resolve_unpacked_extension_origin_matches_versioned_release_folder(tmp_path, folder_name):
    extension_id = "gdjhjiphejeeclngbljhajiffhpdepee"
    extension_path = tmp_path / "Downloads" / folder_name
    _write_preferences(
        tmp_path / "Default",
        "Secure Preferences",
        {extension_id: {"path": str(extension_path)}},
    )

    resolved = resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    assert resolved.extension_id == extension_id
    assert resolved.path == extension_path


@pytest.mark.parametrize(
    "folder_name",
    (
        "other-suno-helper-0.2.5",
        "suno-helper-0.2.5-preview",
        "suno-helper-0..2-chrome",
        "suno-helper-v0.2.5-chrome",
    ),
)
def test_resolve_unpacked_extension_origin_rejects_broad_release_folder_matches(tmp_path, folder_name):
    _write_preferences(
        tmp_path / "Default",
        "Secure Preferences",
        {"gdjhjiphejeeclngbljhajiffhpdepee": {"path": _extension_path(tmp_path, folder_name)}},
    )

    with pytest.raises(ConfigError, match="was not found"):
        resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)


def test_resolve_unpacked_extension_origin_prefers_exact_folder_over_release_folder(tmp_path):
    exact_id = "gdjhjiphejeeclngbljhajiffhpdepee"
    release_id = "abcdefghijklmnopabcdefghijklmnop"
    _write_preferences(
        tmp_path / "Default",
        "Secure Preferences",
        {
            exact_id: {"path": _extension_path(tmp_path, "suno-helper")},
            release_id: {"path": _extension_path(tmp_path, "suno-helper-0.2.5-chrome")},
        },
    )

    resolved = resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    assert resolved.extension_id == exact_id


@pytest.mark.parametrize(
    "disabled_fields",
    (
        {"disable_reasons": [1]},
        {"state": 0},
    ),
)
def test_resolve_unpacked_extension_origin_selects_enabled_duplicate(tmp_path, disabled_fields):
    disabled_id = "gdjhjiphejeeclngbljhajiffhpdepee"
    enabled_id = "abcdefghijklmnopabcdefghijklmnop"
    extension_path = _extension_path(tmp_path, "suno-helper")
    _write_preferences(
        tmp_path / "Default",
        "Secure Preferences",
        {
            disabled_id: {"path": extension_path, **disabled_fields},
            enabled_id: {"path": extension_path},
        },
    )

    resolved = resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    assert resolved.extension_id == enabled_id
    assert resolved.origin == f"chrome-extension://{enabled_id}"


def test_resolve_unpacked_extension_origin_lists_all_disabled_candidates(tmp_path):
    first_id = "gdjhjiphejeeclngbljhajiffhpdepee"
    second_id = "abcdefghijklmnopabcdefghijklmnop"
    first_path = tmp_path / "first" / "suno-helper"
    second_path = tmp_path / "second" / "suno-helper"
    _write_preferences(
        tmp_path / "Default",
        "Secure Preferences",
        {first_id: {"path": str(first_path), "disable_reasons": [1]}},
    )
    _write_preferences(
        tmp_path / "Profile 1",
        "Secure Preferences",
        {second_id: {"path": str(second_path), "state": 0}},
    )

    with pytest.raises(ConfigError) as exc_info:
        resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    message = str(exc_info.value)
    assert "matched no enabled extension IDs" in message
    assert f"profile=Default, id={first_id}, path={first_path}, enabled=false" in message
    assert f"profile=Profile 1, id={second_id}, path={second_path}, enabled=false" in message
    assert "--allow-origin chrome-extension://<EXTENSION_ID>" in message


def test_resolve_unpacked_extension_origin_matches_embedded_manifest_name(tmp_path):
    extension_id = "gdjhjiphejeeclngbljhajiffhpdepee"
    extension_path = tmp_path / "extensions" / "suno-helper" / ".output" / "chrome-mv3"
    _write_preferences(
        tmp_path / "Default",
        "Secure Preferences",
        {
            extension_id: {
                "path": str(extension_path),
                "manifest": {"name": "Suno Helper (youtube-channels-automation)"},
            }
        },
    )

    resolved = resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    assert resolved.extension_id == extension_id
    assert resolved.path == extension_path


@pytest.mark.parametrize(
    "manifest",
    (
        None,
        [],
        {"name": None},
        {"name": "DistroKid Helper (youtube-channels-automation)"},
        {"name": "Suno Helper ("},
        {"name": "Suno Helper (DistroKid Helper"},
        {"name": "Suno Helper () trailing"},
        {"name": "Suno Helper (youtube-channels-automation) trailing"},
    ),
)
def test_resolve_unpacked_extension_origin_rejects_nonmatching_embedded_manifest(tmp_path, manifest):
    extension_path = tmp_path / "extensions" / "suno-helper" / ".output" / "chrome-mv3"
    entry: dict[str, object] = {"path": str(extension_path)}
    if manifest is not None:
        entry["manifest"] = manifest
    _write_preferences(
        tmp_path / "Default",
        "Secure Preferences",
        {"gdjhjiphejeeclngbljhajiffhpdepee": entry},
    )

    with pytest.raises(ConfigError, match="was not found"):
        resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)


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


def test_resolve_unpacked_extension_origin_lists_literal_near_candidates_with_commands(tmp_path):
    enabled_id = "gdjhjiphejeeclngbljhajiffhpdepee"
    disabled_id = "abcdefghijklmnopabcdefghijklmnop"
    enabled_path = tmp_path / "Downloads" / "suno-helper-preview"
    disabled_path = tmp_path / "Downloads" / "my-suno-helper-build"
    _write_preferences(
        tmp_path / "Default",
        "Secure Preferences",
        {
            enabled_id: {"path": str(enabled_path)},
            disabled_id: {"path": str(disabled_path), "state": 0},
        },
    )

    with pytest.raises(ConfigError) as exc_info:
        resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    message = str(exc_info.value)
    assert f"profile=Default, id={enabled_id}, path={enabled_path}, enabled=true" in message
    assert f"--allow-origin chrome-extension://{enabled_id}" in message
    assert f"profile=Default, id={disabled_id}, path={disabled_path}, enabled=false" in message
    assert f"--allow-origin chrome-extension://{disabled_id}" in message


@pytest.mark.parametrize(
    "payload",
    (
        {},
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


def test_resolve_unpacked_extension_origin_selects_first_profile_by_name(tmp_path):
    extension_id = "gdjhjiphejeeclngbljhajiffhpdepee"
    for profile in ("Profile 2", "Profile 10"):
        _write_preferences(
            tmp_path / profile,
            "Secure Preferences",
            {extension_id: {"path": _extension_path(tmp_path, "suno-helper")}},
        )

    resolved = resolve_unpacked_extension_origin("suno-helper", chrome_user_data_dir=tmp_path)

    assert resolved.profile == "Profile 10"


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
    assert "profile=Default, id=gdjhjiphejeeclngbljhajiffhpdepee" in message
    assert "profile=Profile 1, id=abcdefghijklmnopabcdefghijklmnop" in message
    assert message.count("enabled=true") == 2
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
