"""RGB color syntax shared by configuration validation and image rendering."""

from __future__ import annotations

import re

_HEX_COLOR = re.compile(r"^(?:0x|#)?([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?$")
_NAMED_COLORS = {
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
}


def parse_color(value: str, *, allow_named: bool = False) -> tuple[int, int, int]:
    """FFmpeg 形式の RGB hex を RGB tuple に変換する。"""
    match = _HEX_COLOR.fullmatch(value)
    if match:
        rgb = match.group(1)
        return tuple(int(rgb[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
    if allow_named and value.lower() in _NAMED_COLORS:
        return _NAMED_COLORS[value.lower()]
    raise ValueError(f"invalid fill color: {value!r} (expected 0xRRGGBB or #RRGGBB)")


def normalize_ffmpeg_color(value: str) -> str:
    """検証済み色を FFmpeg の ``0xRRGGBB`` 形式へ正規化する。"""
    match = _HEX_COLOR.fullmatch(value)
    if match:
        return f"0x{match.group(1).upper()}"
    if value.lower() in _NAMED_COLORS:
        return value.lower()
    raise ValueError(f"invalid fill color: {value!r} (expected 0xRRGGBB or a basic named color)")
