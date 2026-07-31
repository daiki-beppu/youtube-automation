"""Compatibility package for explicitly supported historical imports."""

from __future__ import annotations

from pathlib import Path

_LEGACY_UTILS_PATH = Path(__file__).parent.parent / "infrastructure" / "legacy_utils"
__path__.append(str(_LEGACY_UTILS_PATH))
