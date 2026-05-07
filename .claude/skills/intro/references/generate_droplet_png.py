#!/usr/bin/env python3
"""Generate the droplet symbol PNG used in intro v7.1+ logo segment.

`branding/intro_assets/05_droplet.png` を生成する (96×96 RGBA, 透明背景,
config.color.droplet 塗り)。`generate_intro.py` の logo segment (15-25s) で
heading 中央に overlay される。

Run once during intro asset preparation; the PNG is committed.

Usage:
    python generate_droplet_png.py
    python generate_droplet_png.py --output <path>  # 出力先を明示指定
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

# `_common` は隣接モジュール (`.claude/skills/intro/references/_common.py`) で、
# `yt-skills sync` 後の配布形態でもテストの `load_skill_script` 経由でも同様に
# 解決できるよう、自スクリプトの親ディレクトリを sys.path に登録してから import する。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import resolve_repo_root  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from youtube_automation.utils.exceptions import ConfigError, ValidationError  # noqa: E402
from youtube_automation.utils.skill_config import load_skill_config  # noqa: E402

# 設計 D の本質的定数
SIZE = 96
SUPER = 4  # 既定の super sampling

_DROPLET_FILENAME = "05_droplet.png"


def _hex_to_rgba(hex_str: str) -> tuple[int, int, int, int]:
    """`#RRGGBB` → `(R, G, B, 255)`。"""
    s = hex_str.strip().lstrip("#")
    if len(s) != 6:
        raise ConfigError(f"color は #RRGGBB 形式である必要があります: {hex_str!r}")
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
    except ValueError as e:
        raise ConfigError(f"color のパースに失敗: {hex_str!r}") from e
    return (r, g, b, 255)


def _teardrop_polygon(width: int, height: int, samples: int = 240) -> list[tuple[float, float]]:
    """Return points tracing a classic teardrop outline (tip points up)."""
    points: list[tuple[float, float]] = []
    cx = width / 2.0
    for i in range(samples + 1):
        t = i / samples
        theta = 2.0 * math.pi * t
        x_norm = math.sin(theta) * math.sin(theta / 2.0)
        y_norm = -math.cos(theta)
        x = cx + x_norm * (width / 2.0)
        y = (y_norm + 1.0) / 2.0 * height
        points.append((x, y))
    return points


def render_droplet(
    out_path: Path,
    *,
    color: tuple[int, int, int, int],
    size: int = SIZE,
    super_sampling: int = SUPER,
) -> None:
    """Render the teardrop PNG at `out_path` with the given RGBA color.

    Args:
        out_path: 出力先 PNG パス (親ディレクトリは自動で mkdir される)
        color: RGBA 4-tuple (各値 0-255)
        size: 出力 PNG の正方形ピクセル
        super_sampling: アンチエイリアス用の超描画倍率

    Raises:
        ValidationError: color tuple の長さが 4 でない
    """
    if not (isinstance(color, tuple) and len(color) == 4):
        raise ValidationError(
            f"color は RGBA 4-tuple である必要があります: {color!r}"
        )

    big = size * super_sampling
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pts = _teardrop_polygon(big, big)
    draw.polygon(pts, fill=color)

    img = img.resize((size, size), Image.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def _resolve_output_path() -> Path:
    """default 出力先 (`<repo>/branding/intro_assets/05_droplet.png`)。"""
    skill_dir = Path(__file__).resolve().parent
    repo = resolve_repo_root(skill_dir)
    return repo / "branding" / "intro_assets" / _DROPLET_FILENAME


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None,
                        help="出力先 PNG パス (default: <repo>/branding/intro_assets/05_droplet.png)")
    args = parser.parse_args()

    cfg = load_skill_config("intro", use_cache=False)
    color = _hex_to_rgba(cfg["color"]["droplet"])
    droplet_cfg = cfg.get("droplet", {})
    size = int(droplet_cfg.get("size", SIZE))
    super_sampling = int(droplet_cfg.get("super_sampling", SUPER))

    out = args.output if args.output else _resolve_output_path()
    render_droplet(out, color=color, size=size, super_sampling=super_sampling)
    print(f"Wrote {out} ({size}x{size} px, transparent bg)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
