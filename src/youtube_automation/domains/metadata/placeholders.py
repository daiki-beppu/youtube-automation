"""Placeholder-value policy used at metadata boundaries."""

from __future__ import annotations

PLACEHOLDER_VALUES = frozenset({"", "tbd", "todo", "fixme", "未定", "要確認", "n/a", "na", "..."})


def is_placeholder_value(value: object) -> bool:
    """Classify an explicitly unresolved metadata value at the boundary."""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return stripped.casefold() in PLACEHOLDER_VALUES or (stripped.startswith("{{") and stripped.endswith("}}"))
