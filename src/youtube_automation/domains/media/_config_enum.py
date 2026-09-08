"""Normalization and diagnostics for named media configuration choices."""

from enum import Enum
from typing import TypeVar

from youtube_automation.core.errors import ConfigError

_EnumT = TypeVar("_EnumT", bound=Enum)


def parse_config_enum(enum_type: type[_EnumT], value: object, *, config_path: str) -> _EnumT:
    """Parse a media choice while retaining its enum type and configuration path."""
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip().lower())
    except ValueError as error:
        allowed = ", ".join(item.value for item in enum_type)
        raise ConfigError(f"{config_path} must be one of: {allowed} (got: {value!r})") from error
