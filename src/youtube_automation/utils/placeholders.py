"""Shared placeholder detection helpers for channel configuration values."""

from __future__ import annotations

PLACEHOLDER_VALUES = frozenset({"", "tbd", "todo", "fixme", "未定", "要確認", "n/a", "na", "..."})


def is_placeholder_value(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return stripped.casefold() in PLACEHOLDER_VALUES or (stripped.startswith("{{") and stripped.endswith("}}"))
