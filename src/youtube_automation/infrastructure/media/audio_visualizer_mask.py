"""Audio visualizer preset masks generated at runtime (#1684)."""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw

VALID_STYLES = ("mirror-mountain", "ring", "ring-line", "heart")
_SIZE_PATTERN = re.compile(r"^(?P<width>[1-9][0-9]*)x(?P<height>[1-9][0-9]*)$")


def parse_size(value: str) -> tuple[int, int]:
    """Parse an FFmpeg ``WIDTHxHEIGHT`` size."""

    match = _SIZE_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"size must be WIDTHxHEIGHT with positive integers: {value!r}")
    return int(match["width"]), int(match["height"])


def _validate(style: str, size: str, bars: int, inner_r: int, length: int, arc_deg: tuple[float, float]) -> None:
    if style not in VALID_STYLES:
        raise ValueError(f"style must be one of {', '.join(VALID_STYLES)}: {style!r}")
    width, height = parse_size(size)
    if bars <= 0:
        raise ValueError("bars must be at least 1")
    if style == "mirror-mountain" and (width % 2 or height % 2):
        raise ValueError("mirror-mountain size width and height must both be even")
    if inner_r < 0 or length <= 0:
        raise ValueError("inner-r must be >= 0 and length must be >= 1")
    if not 0 <= arc_deg[0] < arc_deg[1] <= 360:
        raise ValueError("arc-deg must satisfy 0 <= START < END <= 360")


def _mirror_mask(size: tuple[int, int], bars: int) -> Image.Image:
    width, height = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    cell = width / bars
    gap = max(1, round(cell * 0.24))
    radius = max(1, min(round((cell - gap) * 0.25), height // 8))
    for index in range(bars):
        left = round(index * cell + gap / 2)
        right = round((index + 1) * cell - gap / 2) - 1
        if right >= left:
            draw.rounded_rectangle((left, 0, right, height - 1), radius=radius, fill=255)
    return mask


def _point(center: float, radius: float, degrees: float) -> tuple[float, float]:
    radians = math.radians(degrees - 90)
    return center + radius * math.cos(radians), center + radius * math.sin(radians)


def _ring_mask(style: str, bars: int, inner_r: int, length: int, arc_deg: tuple[float, float]) -> Image.Image:
    outer_r = inner_r + length
    diameter = outer_r * 2
    mask = Image.new("L", (diameter, diameter), 0)
    draw = ImageDraw.Draw(mask)
    center = float(outer_r)
    start, end = arc_deg

    if style == "ring-line":
        draw.pieslice((0, 0, diameter - 1, diameter - 1), start=start - 90, end=end - 90, fill=255)
        inner_box = (center - inner_r, center - inner_r, center + inner_r, center + inner_r)
        draw.ellipse(inner_box, fill=0)
        return mask

    span = end - start
    step = span / bars
    cap_width = max(1, round(math.radians(step) * max(inner_r, 1) * 0.62))
    cap_radius = cap_width / 2
    for index in range(bars):
        angle = start + (index + 0.5) * step
        inner = _point(center, inner_r + cap_radius, angle)
        outer = _point(center, outer_r - cap_radius, angle)
        draw.line((*inner, *outer), fill=255, width=cap_width)
        for x, y in (inner, outer):
            draw.ellipse((x - cap_radius, y - cap_radius, x + cap_radius, y + cap_radius), fill=255)
    return mask


def _heart_mask(size: tuple[int, int], bars: int) -> Image.Image:
    """Draw rounded radial bars centred on ``r = a(1 - sin(theta))``.

    The constants are shared with the FFmpeg ``geq`` mapping in
    ``generate_videos.sh``. Keeping the cardioid and normal span identical
    makes the mask clip each frequency band to one rounded heart-curve bar.
    """

    width, height = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    center_x = width / 2
    center_y = height * 0.66
    cardioid_scale = min(width * 0.24, height * 0.30)
    half_span = min(width, height) * 0.12
    bar_width = max(2, round(min(width, height) * 0.60 / bars))
    cap_radius = bar_width / 2

    for index in range(bars):
        theta = index * math.tau / bars
        curve_radius = cardioid_scale * (1 - math.sin(theta))
        inner_radius = max(0.0, curve_radius - half_span)
        outer_radius = curve_radius + half_span
        cosine = math.cos(theta)
        sine = math.sin(theta)
        inner = (center_x + inner_radius * cosine, center_y + inner_radius * sine)
        outer = (center_x + outer_radius * cosine, center_y + outer_radius * sine)
        draw.line((*inner, *outer), fill=255, width=bar_width)
        for x, y in (inner, outer):
            draw.ellipse((x - cap_radius, y - cap_radius, x + cap_radius, y + cap_radius), fill=255)
    return mask


def generate_mask(
    output: Path,
    *,
    style: str,
    size: str,
    bars: int,
    inner_r: int = 120,
    length: int = 160,
    arc_deg: tuple[float, float] = (0.0, 360.0),
) -> Path:
    """Generate a grayscale mask without external assets or helper scripts."""

    _validate(style, size, bars, inner_r, length, arc_deg)
    if style == "mirror-mountain":
        image = _mirror_mask(parse_size(size), bars)
    elif style == "heart":
        image = _heart_mask(parse_size(size), bars)
    else:
        image = _ring_mask(style, bars, inner_r, length, arc_deg)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a runtime audio visualizer mask")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--style", required=True, choices=VALID_STYLES)
    parser.add_argument("--size", required=True)
    parser.add_argument("--bars", required=True, type=int)
    parser.add_argument("--inner-r", type=int, default=120)
    parser.add_argument("--length", type=int, default=160)
    parser.add_argument("--arc-start", type=float, default=0.0)
    parser.add_argument("--arc-end", type=float, default=360.0)
    args = parser.parse_args()
    generate_mask(
        args.output,
        style=args.style,
        size=args.size,
        bars=args.bars,
        inner_r=args.inner_r,
        length=args.length,
        arc_deg=(args.arc_start, args.arc_end),
    )


if __name__ == "__main__":
    main()
