"""Chrome unpacked extension detection helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from youtube_automation.infrastructure.errors import ConfigError

_CHROME_USER_DATA_RELPATH = Path("Library") / "Application Support" / "Google" / "Chrome"
_EXTENSION_ORIGIN_PREFIX = "chrome-extension://"


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
    preferences_path: Path


def resolve_unpacked_extension_origin(
    extension_name: str,
    *,
    chrome_user_data_dir: Path | None = None,
) -> ChromeExtensionOrigin:
    """Resolve an unpacked Chrome extension basename to a chrome-extension origin."""

    if not extension_name:
        raise ConfigError("Chrome extension name must not be empty. Use --allow-origin for manual fallback.")

    root = chrome_user_data_dir if chrome_user_data_dir is not None else Path.home() / _CHROME_USER_DATA_RELPATH
    candidates = _find_unpacked_extension_candidates(extension_name, root)
    if not candidates:
        raise ConfigError(
            f"Chrome unpacked extension named {extension_name!r} was not found in {root}. "
            "Load the unpacked extension in Chrome, or pass --allow-origin chrome-extension://<EXTENSION_ID> manually."
        )

    ids = {candidate.extension_id for candidate in candidates}
    if len(ids) > 1:
        raise ConfigError(
            f"Chrome unpacked extension named {extension_name!r} matched multiple extension IDs. "
            f"Candidates: {_format_candidates(candidates)}. "
            "Pass --allow-origin chrome-extension://<EXTENSION_ID> manually."
        )

    selected = candidates[0]
    return ChromeExtensionOrigin(
        name=extension_name,
        extension_id=selected.extension_id,
        origin=f"{_EXTENSION_ORIGIN_PREFIX}{selected.extension_id}",
        profile=selected.profile,
        path=selected.path,
    )


def _find_unpacked_extension_candidates(extension_name: str, root: Path) -> list[_ExtensionCandidate]:
    candidates: list[_ExtensionCandidate] = []
    for profile_dir in _iter_profile_dirs(root):
        preferences_path = _preferences_path(profile_dir)
        if preferences_path is None:
            continue
        payload = _read_preferences(preferences_path)
        candidates.extend(_candidates_from_preferences(extension_name, profile_dir, preferences_path, payload))
    return candidates


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
        if not extension_path.is_absolute() or extension_path.name != extension_name:
            continue
        candidates.append(
            _ExtensionCandidate(
                extension_id=extension_id,
                profile=profile_dir.name,
                path=extension_path,
                preferences_path=preferences_path,
            )
        )
    return candidates


def _format_candidates(candidates: list[_ExtensionCandidate]) -> str:
    return "; ".join(
        f"{candidate.profile}: {candidate.extension_id} ({candidate.path}) via {candidate.preferences_path}"
        for candidate in candidates
    )
