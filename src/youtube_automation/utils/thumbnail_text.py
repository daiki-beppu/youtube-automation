"""サムネイルテキストの決定的合成 (#1332)

AI 画像生成 (Gemini / OpenAI / codex) はプロンプトでフォント名を指示しても
書体を厳密に再現できず、同一チャンネルでもサムネの文字フォントが毎回
バラつく。本モジュールは textless 背景 (main.png/jpg 系) に実フォント
ファイル (.ttf / .otf / .ttc) を Pillow で描画することで、同一設定なら
ピクセル単位で再現される決定的なテキスト合成経路を提供する。

設定は CLI 境界で provider 固有 namespace から取り出した overlay mapping を受け取る。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont, UnidentifiedImageError

from youtube_automation.utils.exceptions import ConfigError

# 出力サムネの標準サイズ (YouTube 推奨 1280x720) を基準にした既定値
_DEFAULT_TITLE_SIZE = 96
_DEFAULT_CHANNEL_NAME_SIZE = 36
_DEFAULT_COLOR = "#FFFFFF"
_DEFAULT_STROKE_COLOR = "#000000"
_OVERLAY_CONFIG_PREFIX = "image_generation.gemini.thumbnail_text.overlay"

_VALID_ANCHORS = frozenset(
    {
        "top-left",
        "top-center",
        "top-right",
        "center-left",
        "center",
        "center-right",
        "bottom-left",
        "bottom-center",
        "bottom-right",
    }
)

# フォント解決失敗時に案内する代替手順 (#1332 受け入れ条件)
_FONT_FALLBACK_GUIDANCE = (
    "対処:\n"
    "  1. config/skills/thumbnail.yaml の image_generation.gemini.thumbnail_text.overlay.font.title に対応する\n"
    "     .ttf / .otf / .ttc ファイルのパスを設定する (絶対パス、または channel_dir からの相対パス)\n"
    '     例) font: {title: "assets/fonts/NotoSansJP-Bold.ttf"}\n'
    "  2. 利用可能なフォントの例: macOS は /System/Library/Fonts/、Google Fonts から\n"
    "     ダウンロードしたファイルを <channel_dir>/assets/fonts/ に置く運用を推奨\n"
    "  3. 決定的合成を使わない場合は AI 経路にフォールバックする\n"
    "     (SKILL.md「フォント安定化」参照。single_step の typography_clause / two_phase の\n"
    "     thumbnail_text.font でフォントの雰囲気を指示できるが、書体の厳密な再現は保証されない)"
)

_SKILL_CONFIG_PATH_HINT = "config/skills/thumbnail.yaml"


@dataclass(frozen=True)
class TextStyle:
    """1 テキスト要素分の描画スタイル。"""

    font_path: Path
    size: int
    color: str
    stroke_width: int
    stroke_color: str


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


def resolve_font_path(raw: str, *, channel_root: Path, key: str) -> Path:
    """設定値のフォントパスを検証込みで解決する。

    絶対パスはそのまま、相対パスは channel_dir 起点で解決する。
    未設定・実在しないパスは理由と代替手順つきの ConfigError にする。
    """
    if not raw or not raw.strip():
        raise ConfigError(f"フォント指定が未設定です: {key}\n{_FONT_FALLBACK_GUIDANCE}")
    candidate = Path(raw.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = channel_root / candidate
    if not candidate.is_file():
        raise ConfigError(f"フォントファイルが見つかりません: {key} = {candidate}\n{_FONT_FALLBACK_GUIDANCE}")
    return candidate


def load_font(style: TextStyle) -> ImageFont.FreeTypeFont:
    """TextStyle からフォントをロードする。ロード不能なら ConfigError。"""
    try:
        return ImageFont.truetype(str(style.font_path), style.size)
    except OSError as exc:
        raise ConfigError(
            f"フォントファイルを読み込めません: {style.font_path} ({exc})\n{_FONT_FALLBACK_GUIDANCE}"
        ) from exc


def _parse_color(raw: object, *, default: str, key: str) -> str:
    value = default if raw in (None, "") else str(raw)
    try:
        ImageColor.getrgb(value)
    except ValueError as exc:
        raise ConfigError(f'色指定が不正です: {key} = {value!r} (例: "#FFFFFF" / "white")') from exc
    return value


def _parse_int(raw: object, *, default: int, key: str, minimum: int = 0) -> int:
    if raw in (None, ""):
        return default
    if isinstance(raw, bool):
        raise ConfigError(f"整数を指定してください: {key} = {raw!r}")
    if isinstance(raw, float):
        if not math.isfinite(raw):
            raise ConfigError(f"{key} は有限の整数を指定してください: {raw!r}")
        if not raw.is_integer():
            raise ConfigError(f"整数を指定してください: {key} = {raw!r}")
    try:
        value = int(raw)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ConfigError(f"整数を指定してください: {key} = {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{key} は {minimum} 以上を指定してください: {value}")
    return value


def _mapping_at(parent: Mapping[str, object], name: str, *, key: str) -> Mapping[str, object]:
    """Optional mapping section reader.

    Missing keys inherit defaults, but explicitly provided non-mapping values are
    configuration errors so typos do not silently fall back to defaults.
    """
    if name not in parent:
        return {}
    value = parent[name]
    if not isinstance(value, Mapping):
        raise ConfigError(f"{key} はマッピングで指定してください ({_SKILL_CONFIG_PATH_HINT})")
    return value


def _parse_positive_float(raw: object, *, default: float, key: str) -> float:
    if raw in (None, ""):
        return default
    if isinstance(raw, bool):
        raise ConfigError(f"数値を指定してください: {key} = {raw!r}")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"数値を指定してください: {key} = {raw!r}") from exc
    if not math.isfinite(value):
        raise ConfigError(f"{key} は有限の数値を指定してください: {value!r}")
    if value <= 0:
        raise ConfigError(f"{key} は正の数を指定してください: {value}")
    return value


def _font_path_value(font_cfg: Mapping[str, object], name: str, *, key: str) -> str:
    raw = font_cfg.get(name)
    if raw in (None, ""):
        return ""
    if not isinstance(raw, str):
        raise ConfigError(f"フォントパスは文字列で指定してください: {key} = {raw!r}")
    return raw


def _build_text_style(
    section: Mapping[str, object],
    *,
    font_raw: str,
    channel_root: Path,
    key_prefix: str,
    font_key: str,
    default_size: int,
    default_stroke_width: int,
) -> TextStyle:
    return TextStyle(
        font_path=resolve_font_path(font_raw, channel_root=channel_root, key=font_key),
        size=_parse_int(section.get("size"), default=default_size, key=f"{key_prefix}.size", minimum=1),
        color=_parse_color(section.get("color"), default=_DEFAULT_COLOR, key=f"{key_prefix}.color"),
        stroke_width=_parse_int(
            section.get("stroke_width"),
            default=default_stroke_width,
            key=f"{key_prefix}.stroke_width",
        ),
        stroke_color=_parse_color(
            section.get("stroke_color"),
            default=_DEFAULT_STROKE_COLOR,
            key=f"{key_prefix}.stroke_color",
        ),
    )


def overlay_spec_from_overlay_config(
    overlay_config: Mapping[str, object],
    *,
    channel_root: Path,
    with_channel_name: bool,
) -> OverlaySpec:
    """Provider 非依存の overlay mapping から OverlaySpec を組み立てる。

    フォント未設定などの不備は ConfigError (理由 + 代替手順つき) にする。
    """
    if not isinstance(overlay_config, Mapping):
        raise ConfigError(f"{_OVERLAY_CONFIG_PREFIX} はマッピングで指定してください ({_SKILL_CONFIG_PATH_HINT})")

    prefix = _OVERLAY_CONFIG_PREFIX
    font_cfg = _mapping_at(overlay_config, "font", key=f"{prefix}.font")
    title_cfg = _mapping_at(overlay_config, "title", key=f"{prefix}.title")
    channel_cfg = _mapping_at(overlay_config, "channel_name", key=f"{prefix}.channel_name")
    title_font_raw = _font_path_value(font_cfg, "title", key=f"{prefix}.font.title")

    title_style = _build_text_style(
        title_cfg,
        font_raw=title_font_raw,
        channel_root=channel_root,
        key_prefix=f"{prefix}.title",
        font_key=f"{prefix}.font.title",
        default_size=_DEFAULT_TITLE_SIZE,
        default_stroke_width=4,
    )

    channel_name_style: TextStyle | None = None
    if with_channel_name:
        # channel_name 用フォント未設定時はタイトルフォントを継承する
        channel_font_raw = _font_path_value(font_cfg, "channel_name", key=f"{prefix}.font.channel_name")
        if not channel_font_raw:
            channel_font_raw = title_font_raw
        channel_name_style = _build_text_style(
            channel_cfg,
            font_raw=channel_font_raw,
            channel_root=channel_root,
            key_prefix=f"{prefix}.channel_name",
            font_key=f"{prefix}.font.channel_name",
            default_size=_DEFAULT_CHANNEL_NAME_SIZE,
            default_stroke_width=0,
        )

    layout = _mapping_at(overlay_config, "layout", key=f"{prefix}.layout")
    anchor = str(layout.get("anchor") or "bottom-center")
    if anchor not in _VALID_ANCHORS:
        raise ConfigError(
            f"{prefix}.layout.anchor が不正です: {anchor!r} (指定可能: {', '.join(sorted(_VALID_ANCHORS))})"
        )

    line_spacing = _parse_positive_float(
        layout.get("line_spacing"),
        default=1.15,
        key=f"{prefix}.layout.line_spacing",
    )

    return OverlaySpec(
        title_style=title_style,
        channel_name_style=channel_name_style,
        anchor=anchor,
        margin_x=_parse_int(layout.get("margin_x"), default=64, key=f"{prefix}.layout.margin_x"),
        margin_y=_parse_int(layout.get("margin_y"), default=48, key=f"{prefix}.layout.margin_y"),
        line_spacing=line_spacing,
        gap=_parse_int(layout.get("gap"), default=24, key=f"{prefix}.layout.gap"),
    )


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
