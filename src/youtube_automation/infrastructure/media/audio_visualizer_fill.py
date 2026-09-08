"""Audio visualizer の gradient / conical fill を実行時生成する。"""

from __future__ import annotations

import colorsys
import re
from pathlib import Path

from PIL import Image

from youtube_automation.core.colors import (
    normalize_ffmpeg_color as normalize_ffmpeg_color,
)
from youtube_automation.core.colors import (
    parse_color as parse_color,
)


def parse_size(value: str) -> tuple[int, int]:
    """``WIDTHxHEIGHT`` を正の整数 tuple に変換する。"""
    match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", value)
    if not match:
        raise ValueError(f"invalid visualizer size: {value!r} (expected WIDTHxHEIGHT)")
    return int(match.group(1)), int(match.group(2))


def create_fill_asset(
    fill_type: str,
    size: str,
    output: Path,
    *,
    color: str = "white",
    top: str = "0xA9CBF0",
    bottom: str = "0x3A5696",
) -> str:
    """fill asset を生成し、縮退後の type を返す。"""
    width, height = parse_size(size)
    if fill_type not in {"solid", "gradient", "rainbow", "conical"}:
        raise ValueError(f"invalid fill type: {fill_type!r} (expected solid, gradient, rainbow, or conical)")
    if fill_type == "solid":
        normalize_ffmpeg_color(color)
        return "solid"

    if fill_type == "gradient":
        top_rgb = parse_color(top)
        bottom_rgb = parse_color(bottom)
        if top_rgb == bottom_rgb:
            return "solid"
        image = Image.new("RGB", (width, height))
        pixels = image.load()
        divisor = max(height - 1, 1)
        for y in range(height):
            ratio = y / divisor
            row_color = tuple(round(a + (b - a) * ratio) for a, b in zip(top_rgb, bottom_rgb, strict=True))
            for x in range(width):
                pixels[x, y] = row_color
    else:
        image = Image.new("RGB", (width, height))
        pixels = image.load()
        center_x = (width - 1) / 2
        center_y = (height - 1) / 2
        import math

        for y in range(height):
            for x in range(width):
                hue = (math.atan2(y - center_y, x - center_x) / (2 * math.pi)) % 1.0
                pixels[x, y] = tuple(round(channel * 255) for channel in colorsys.hsv_to_rgb(hue, 1.0, 1.0))

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG")
    return fill_type
