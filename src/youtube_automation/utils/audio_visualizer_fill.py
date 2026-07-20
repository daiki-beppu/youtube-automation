"""Audio visualizer の gradient / conical fill を実行時生成する。"""

from __future__ import annotations

import argparse
import colorsys
import re
from pathlib import Path

from PIL import Image

_HEX_COLOR = re.compile(r"^(?:0x|#)?([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?$")
_NAMED_COLORS = {"white", "black", "red", "green", "blue", "yellow", "cyan", "magenta"}


def parse_size(value: str) -> tuple[int, int]:
    """``WIDTHxHEIGHT`` を正の整数 tuple に変換する。"""
    match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", value)
    if not match:
        raise ValueError(f"invalid visualizer size: {value!r} (expected WIDTHxHEIGHT)")
    return int(match.group(1)), int(match.group(2))


def parse_color(value: str, *, allow_named: bool = False) -> tuple[int, int, int]:
    """FFmpeg 形式の RGB hex を Pillow 用 tuple に変換する。"""
    match = _HEX_COLOR.fullmatch(value)
    if match:
        rgb = match.group(1)
        return tuple(int(rgb[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
    if allow_named and value.lower() in _NAMED_COLORS:
        image = Image.new("RGB", (1, 1), value.lower())
        return image.getpixel((0, 0))
    raise ValueError(f"invalid fill color: {value!r} (expected 0xRRGGBB or #RRGGBB)")


def normalize_ffmpeg_color(value: str) -> str:
    """検証済み色を FFmpeg の ``0xRRGGBB`` 形式へ正規化する。"""
    match = _HEX_COLOR.fullmatch(value)
    if match:
        return f"0x{match.group(1).upper()}"
    if value.lower() in _NAMED_COLORS:
        return value.lower()
    raise ValueError(f"invalid fill color: {value!r} (expected 0xRRGGBB or a basic named color)")


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", required=True, choices=("solid", "gradient", "rainbow", "conical"))
    parser.add_argument("--size", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--color", default="white")
    parser.add_argument("--top", default="0xA9CBF0")
    parser.add_argument("--bottom", default="0x3A5696")
    args = parser.parse_args()
    try:
        effective_type = create_fill_asset(
            args.type, args.size, args.output, color=args.color, top=args.top, bottom=args.bottom
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(effective_type)


if __name__ == "__main__":
    main()
