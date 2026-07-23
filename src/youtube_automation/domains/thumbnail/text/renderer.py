from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from youtube_automation.domains.thumbnail.text.models import OverlaySpec, TextStyle
from youtube_automation.utils.exceptions import ConfigError, ValidationError

_FINAL_THUMBNAIL_NAMES = frozenset({"thumbnail.jpg", "thumbnail.jpeg", "thumbnail.png"})
_ALLOWED_OUTPUT_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})
_MAX_BACKGROUND_BYTES = 32 * 1024 * 1024
_MAX_BACKGROUND_PIXELS = 16_000_000


def load_font(style: TextStyle) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(style.font_path), style.size)
    except OSError as exc:
        raise ConfigError(f"フォントファイルを読み込めません: {style.font_path} ({exc})") from exc


def _line_height(font: ImageFont.FreeTypeFont) -> int:
    ascent, descent = font.getmetrics()
    return ascent + descent


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, stroke_width: int) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    return right - left


def _absolute_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return Path.cwd() / expanded


def _has_symlink_parent(path: Path) -> bool:
    current = path.parent
    while current != current.parent:
        if current.is_symlink():
            return True
        current = current.parent
    return False


def validate_thumbnail_output_path(output: Path, *, channel_root: Path) -> None:
    final_names = ", ".join(sorted(_FINAL_THUMBNAIL_NAMES))
    if output.name.lower() in _FINAL_THUMBNAIL_NAMES:
        raise ValidationError(
            f"最終サムネイル名への直接出力はできません: {output} "
            f"(候補名 thumbnail-v1.jpg などへ出力し、承認後に {final_names} へコピーしてください)"
        )
    if output.is_symlink():
        raise ValidationError(f"出力先にシンボリックリンクは指定できません: {output}")
    if output.exists():
        raise ValidationError(
            f"出力先ファイルは既に存在します: {output} (候補名を変えるか、不要な候補を削除してください)"
        )
    if output.suffix.lower() not in _ALLOWED_OUTPUT_SUFFIXES:
        allowed = ", ".join(sorted(_ALLOWED_OUTPUT_SUFFIXES))
        raise ValidationError(f"出力先の拡張子は {allowed} のいずれかを指定してください: {output}")

    output_abs = _absolute_path(output)
    if _has_symlink_parent(output_abs):
        raise ValidationError(f"出力先の親ディレクトリにシンボリックリンクは指定できません: {output}")

    channel_root_resolved = channel_root.resolve()
    output_resolved = output_abs.resolve(strict=False)
    if not output_resolved.is_relative_to(channel_root_resolved):
        raise ValidationError(
            f"出力先は channel_dir 配下に指定してください: {output} (channel_dir: {channel_root_resolved})"
        )


def _image_format_for_suffix(output: Path) -> str:
    if output.suffix.lower() in {".jpg", ".jpeg"}:
        return "JPEG"
    return "PNG"


def _relative_output_parts(output: Path, *, channel_root: Path) -> tuple[str, ...]:
    channel_root_resolved = channel_root.resolve()
    output_abs = _absolute_path(output)
    try:
        relative = output_abs.relative_to(channel_root_resolved)
    except ValueError as exc:
        raise ValidationError(
            f"出力先は channel_dir 配下に指定してください: {output} (channel_dir: {channel_root_resolved})"
        ) from exc
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValidationError(f"出力先パスが不正です: {output}")
    return parts


def _directory_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _open_or_create_dir_at(parent_fd: int, name: str, *, output: Path) -> int:
    flags = _directory_flags()
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(name, 0o777, dir_fd=parent_fd)
            return os.open(name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise ValidationError(f"出力画像を保存できません: {output} ({exc})") from exc
    except OSError as exc:
        raise ValidationError(f"出力画像を保存できません: {output} ({exc})") from exc


def _open_output_parent_dir(output: Path, *, channel_root: Path) -> int:
    parts = _relative_output_parts(output, channel_root=channel_root)
    try:
        current_fd = os.open(channel_root.resolve(), _directory_flags())
    except OSError as exc:
        raise ValidationError(f"出力画像を保存できません: {output} ({exc})") from exc

    for part in parts[:-1]:
        try:
            next_fd = _open_or_create_dir_at(current_fd, part, output=output)
        finally:
            os.close(current_fd)
        current_fd = next_fd
    return current_fd


def _open_output_file_no_follow(output: Path, *, channel_root: Path):
    validate_thumbnail_output_path(output, channel_root=channel_root)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    if os.open not in os.supports_dir_fd or os.mkdir not in os.supports_dir_fd:
        raise ValidationError("出力画像を保存できません: fd-based の安全なファイル作成を利用できません")

    dir_fd = _open_output_parent_dir(output, channel_root=channel_root)
    try:
        try:
            file_fd = os.open(output.name, flags, 0o666, dir_fd=dir_fd)
        except OSError as exc:
            raise ValidationError(f"出力画像を保存できません: {output} ({exc})") from exc
    finally:
        os.close(dir_fd)
    return os.fdopen(file_fd, "wb")


def _save_image_safely(image: Image.Image, output: Path, *, channel_root: Path) -> None:
    image_format = _image_format_for_suffix(output)
    try:
        with _open_output_file_no_follow(output, channel_root=channel_root) as fh:
            if image_format == "JPEG":
                image.save(fh, format=image_format, quality=95)
            else:
                image.save(fh, format=image_format)
    except (OSError, ValueError) as exc:
        if output.exists() and not output.is_symlink():
            output.unlink()
        raise ValidationError(f"出力画像を保存できません: {output} ({exc})") from exc


def _validate_background_file(background: Path) -> None:
    try:
        size = background.stat().st_size
    except OSError as exc:
        raise ValidationError(f"背景画像を読み込めません: {background} ({exc})") from exc
    if size > _MAX_BACKGROUND_BYTES:
        raise ValidationError(
            f"背景画像のファイルサイズが大きすぎます: {background} ({size} bytes > {_MAX_BACKGROUND_BYTES} bytes)"
        )


def _validate_background_pixels(image: Image.Image, *, background: Path) -> None:
    width, height = image.size
    pixels = width * height
    if pixels > _MAX_BACKGROUND_PIXELS:
        raise ValidationError(
            f"背景画像のピクセル数が大きすぎます: {background} "
            f"({width}x{height} = {pixels} pixels > {_MAX_BACKGROUND_PIXELS} pixels)"
        )


def compose_thumbnail_text(
    *,
    background: Path,
    output: Path,
    channel_root: Path,
    spec: OverlaySpec,
    title_lines: list[str],
    channel_name: str | None = None,
) -> Path:
    if not background.is_file():
        raise ValidationError(f"背景画像が見つかりません: {background}")
    lines = [line for line in (s.strip() for s in title_lines) if line]
    if not lines:
        raise ValidationError("タイトル行が空です。--title で 1 行以上指定してください")
    if channel_name and spec.channel_name_style is None:
        raise ValidationError("channel_name 指定時は OverlaySpec.channel_name_style が必要です")
    validate_thumbnail_output_path(output, channel_root=channel_root)

    title_font = load_font(spec.title_style)
    channel_font = load_font(spec.channel_name_style) if channel_name and spec.channel_name_style else None

    _validate_background_file(background)
    try:
        with Image.open(background) as opened:
            _validate_background_pixels(opened, background=background)
            image = opened.convert("RGB")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValidationError(f"背景画像を読み込めません: {background} ({exc})") from exc
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

    _save_image_safely(image, output, channel_root=channel_root)
    return output
