from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TextStyle:
    font_path: Path
    size: int
    color: str
    stroke_width: int
    stroke_color: str


@dataclass(frozen=True)
class OverlaySpec:
    title_style: TextStyle
    channel_name_style: TextStyle | None
    anchor: str
    margin_x: int
    margin_y: int
    line_spacing: float
    gap: int
