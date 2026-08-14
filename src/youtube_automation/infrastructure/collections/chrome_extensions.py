"""Chrome unpacked extension detection helpers."""

from __future__ import annotations

import json
import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path

from youtube_automation.core.errors import ConfigError

_EXTENSION_ORIGIN_PREFIX = "chrome-extension://"


def _default_chrome_user_data_dir() -> Path:
    """OS 別の Chrome User Data ディレクトリを返す。"""

    system = platform.system()
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "Google" / "Chrome" / "User Data"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    return Path.home() / ".config" / "google-chrome"


@dataclass(frozen=True)
class ChromeExtensionOrigin:
    """Resolved unpacked Chrome extension origin."""

    name: str
    extension_id: str
    origin: str
    profile: str
    path: Path


@dataclass(frozen=True)
class _ExtensionCandidate:
    extension_id: str
    profile: str
    path: Path
    enabled: bool
    preferences_path: Path
    match_priority: int | None


def resolve_unpacked_extension_origin(
    extension_name: str,
    *,
    chrome_user_data_dir: Path | None = None,
) -> ChromeExtensionOrigin:
    """Resolve an unpacked Chrome extension basename to a chrome-extension origin."""

    if not extension_name:
        raise ConfigError("Chrome extension name must not be empty. Use --allow-origin for manual fallback.")

    root = chrome_user_data_dir if chrome_user_data_dir is not None else _default_chrome_user_data_dir()
    candidates, near_candidates = _find_unpacked_extension_candidates(extension_name, root)
    if not candidates:
        near_candidate_guidance = (
            f" Nearby unpacked extensions: {_format_near_candidates(near_candidates)}." if near_candidates else ""
        )
        raise ConfigError(
            f"Chrome unpacked extension named {extension_name!r} was not found in {root}. "
            f"Load the unpacked extension in Chrome.{near_candidate_guidance} "
            "Otherwise pass --allow-origin chrome-extension://<EXTENSION_ID> manually."
        )

    enabled_candidates = [candidate for candidate in candidates if candidate.enabled]
    if not enabled_candidates:
        raise ConfigError(
            f"Chrome unpacked extension named {extension_name!r} matched no enabled extension IDs. "
            f"Candidates: {_format_candidates(candidates)}. "
            "Pass --allow-origin chrome-extension://<EXTENSION_ID> manually."
        )

    ids = {candidate.extension_id for candidate in enabled_candidates}
    if len(ids) > 1:
        raise ConfigError(
            f"Chrome unpacked extension named {extension_name!r} matched multiple extension IDs. "
            f"Candidates: {_format_candidates(candidates)}. "
            "Pass --allow-origin chrome-extension://<EXTENSION_ID> manually."
        )

    selected = enabled_candidates[0]
    return ChromeExtensionOrigin(
        name=extension_name,
        extension_id=selected.extension_id,
        origin=f"{_EXTENSION_ORIGIN_PREFIX}{selected.extension_id}",
        profile=selected.profile,
        path=selected.path,
    )


def _find_unpacked_extension_candidates(
    extension_name: str,
    root: Path,
) -> tuple[list[_ExtensionCandidate], list[_ExtensionCandidate]]:
    discovered: list[_ExtensionCandidate] = []
    for profile_dir in _iter_profile_dirs(root):
        preferences_path = _preferences_path(profile_dir)
        if preferences_path is None:
            continue
        payload = _read_preferences(preferences_path)
        discovered.extend(_candidates_from_preferences(extension_name, profile_dir, preferences_path, payload))

    priorities = [candidate.match_priority for candidate in discovered if candidate.match_priority is not None]
    if priorities:
        selected_priority = min(priorities)
        return (
            [candidate for candidate in discovered if candidate.match_priority == selected_priority],
            [],
        )
    return [], [candidate for candidate in discovered if extension_name in candidate.path.name]


def _iter_profile_dirs(root: Path) -> list[Path]:
    try:
        if not root.is_dir():
            return []
        return sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name)
    except OSError as exc:
        raise ConfigError(
            f"Failed to scan Chrome profiles at {root}: {exc}. "
            "Pass --allow-origin chrome-extension://<EXTENSION_ID> manually."
        ) from exc


def _preferences_path(profile_dir: Path) -> Path | None:
    secure_preferences = profile_dir / "Secure Preferences"
    if secure_preferences.is_file():
        return secure_preferences
    preferences = profile_dir / "Preferences"
    if preferences.is_file():
        return preferences
    return None


def _read_preferences(preferences_path: Path) -> object:
    try:
        return json.loads(preferences_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(
            f"Failed to read Chrome preferences at {preferences_path}: {exc}. "
            "Pass --allow-origin chrome-extension://<EXTENSION_ID> manually."
        ) from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"Failed to parse Chrome preferences at {preferences_path}: {exc}. "
            "Pass --allow-origin chrome-extension://<EXTENSION_ID> manually."
        ) from exc


def _candidates_from_preferences(
    extension_name: str,
    profile_dir: Path,
    preferences_path: Path,
    payload: object,
) -> list[_ExtensionCandidate]:
    if not isinstance(payload, dict):
        return []
    extensions = payload.get("extensions")
    if not isinstance(extensions, dict):
        return []
    settings = extensions.get("settings")
    if not isinstance(settings, dict):
        return []

    candidates: list[_ExtensionCandidate] = []
    for extension_id, raw_entry in settings.items():
        if not isinstance(extension_id, str) or not isinstance(raw_entry, dict):
            continue
        raw_path = raw_entry.get("path")
        if not isinstance(raw_path, str):
            continue
        extension_path = Path(raw_path)
        if not extension_path.is_absolute():
            continue
        match_priority = _extension_name_match_priority(extension_name, extension_path, raw_entry)
        if match_priority is None and extension_name not in extension_path.name:
            continue
        candidates.append(
            _ExtensionCandidate(
                extension_id=extension_id,
                profile=profile_dir.name,
                path=extension_path,
                enabled=not _is_disabled_extension_entry(raw_entry),
                preferences_path=preferences_path,
                match_priority=match_priority,
            )
        )
    return candidates


def _is_disabled_extension_entry(raw_entry: dict[object, object]) -> bool:
    return bool(raw_entry.get("disable_reasons")) or raw_entry.get("state") == 0


def _extension_name_match_priority(
    extension_name: str,
    extension_path: Path,
    raw_entry: dict[object, object],
) -> int | None:
    if extension_path.name == extension_name:
        return 0
    release_folder_pattern = rf"{re.escape(extension_name)}(?:-\d+(?:\.\d+)*)?(?:-chrome)?"
    if re.fullmatch(release_folder_pattern, extension_path.name):
        return 1
    manifest = raw_entry.get("manifest")
    if not isinstance(manifest, dict):
        return None
    manifest_name = manifest.get("name")
    if not isinstance(manifest_name, str):
        return None
    requested_name = " ".join(extension_name.replace("-", " ").split()).casefold()
    display_name = " ".join(manifest_name.split()).casefold()
    if display_name in {requested_name, f"{requested_name} (youtube-channels-automation)"}:
        return 2
    return None


def _format_candidates(candidates: list[_ExtensionCandidate]) -> str:
    return "; ".join(
        f"profile={candidate.profile}, id={candidate.extension_id}, path={candidate.path}, "
        f"enabled={str(candidate.enabled).lower()}, preferences={candidate.preferences_path}"
        for candidate in candidates
    )


def _format_near_candidates(candidates: list[_ExtensionCandidate]) -> str:
    return "; ".join(
        f"profile={candidate.profile}, id={candidate.extension_id}, path={candidate.path}, "
        f"enabled={str(candidate.enabled).lower()}, "
        f"command=yt-collection-serve --allow-origin {_EXTENSION_ORIGIN_PREFIX}{candidate.extension_id}"
        for candidate in candidates
    )
