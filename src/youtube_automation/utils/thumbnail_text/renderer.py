"""Pillow によるサムネイルテキスト描画。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from youtube_automation.utils.exceptions import ConfigError
from youtube_automation.utils.thumbnail_text.config import _font_fallback_guidance
from youtube_automation.utils.thumbnail_text.models import OverlaySpec, TextStyle


def load_font(style: TextStyle) -> ImageFont.FreeTypeFont:
    """TextStyle からフォントをロードする。ロード不能なら ConfigError。"""
    try:
        return ImageFont.truetype(str(style.font_path), style.size)
    except OSError as exc:
        raise ConfigError(
            f"フォントファイルを読み込めません: {style.font_path} ({exc})\n{_font_fallback_guidance(style.font_key)}"
        ) from exc


def _line_height(font: ImageFont.FreeTypeFont) -> int:
    ascent, descent = font.getmetrics()
    return ascent + descent


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, stroke_width: int) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    return right - left


def compose_thumbnail_text(
    *,
    background: Path,
    output: Path,
    spec: OverlaySpec,
    title_lines: list[str],
    channel_name: str | None = None,
) -> Path:
    """textless 背景にタイトル (+ チャンネル名) を決定的に描画して保存する。

    同一の背景・テキスト・設定なら常に同一の出力になる (AI 生成に依存しない)。
    """
    if not background.is_file():
        raise ConfigError(f"背景画像が見つかりません: {background}")
    lines = [line for line in (s.strip() for s in title_lines) if line]
    if not lines:
        raise ConfigError("タイトル行が空です。--title で 1 行以上指定してください")
    if channel_name and spec.channel_name_style is None:
        raise ConfigError("channel_name 指定時は OverlaySpec.channel_name_style が必要です")

    title_font = load_font(spec.title_style)
    channel_font = load_font(spec.channel_name_style) if channel_name and spec.channel_name_style else None

    try:
        image = Image.open(background).convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise ConfigError(f"背景画像を読み込めません: {background} ({exc})") from exc
    draw = ImageDraw.Draw(image)

    title_line_height = round(_line_height(title_font) * spec.line_spacing)
    block_height = title_line_height * len(lines)
    if channel_font is not None:
        block_height += spec.gap + _line_height(channel_font)

    vertical, _, horizontal = spec.anchor.partition("-")
    if not horizontal:
        vertical, horizontal = "center", "center"  # anchor == "center"

    if vertical == "top":
        y = spec.margin_y
    elif vertical == "bottom":
        y = image.height - spec.margin_y - block_height
    else:
        y = (image.height - block_height) // 2

    def _x_for(width: int) -> int:
        if horizontal == "left":
            return spec.margin_x
        if horizontal == "right":
            return image.width - spec.margin_x - width
        return (image.width - width) // 2

    for line in lines:
        width = _text_width(draw, line, title_font, spec.title_style.stroke_width)
        draw.text(
            (_x_for(width), y),
            line,
            font=title_font,
            fill=spec.title_style.color,
            stroke_width=spec.title_style.stroke_width,
            stroke_fill=spec.title_style.stroke_color,
        )
        y += title_line_height

    if channel_font is not None and channel_name and spec.channel_name_style is not None:
        y += spec.gap
        width = _text_width(draw, channel_name, channel_font, spec.channel_name_style.stroke_width)
        draw.text(
            (_x_for(width), y),
            channel_name,
            font=channel_font,
            fill=spec.channel_name_style.color,
            stroke_width=spec.channel_name_style.stroke_width,
            stroke_fill=spec.channel_name_style.stroke_color,
        )

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.suffix.lower() in {".jpg", ".jpeg"}:
            image.save(output, format="JPEG", quality=95)
        else:
            image.save(output)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"出力画像を保存できません: {output} ({exc})") from exc
    return output
