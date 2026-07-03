"""サムネイルテキスト合成の値オブジェクト。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TextStyle:
    """1 テキスト要素分の描画スタイル。"""

    font_path: Path
    size: int
    color: str
    stroke_width: int
    stroke_color: str
    font_key: str = "font"


@dataclass(frozen=True)
class OverlaySpec:
    """テキスト合成 1 回分の描画仕様。"""

    title_style: TextStyle
    channel_name_style: TextStyle | None
    anchor: str
    margin_x: int
    margin_y: int
    line_spacing: float
    gap: int
