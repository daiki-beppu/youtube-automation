from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path

from PIL import ImageColor, ImageFont

from youtube_automation.domains.thumbnail.text.models import OverlaySpec, TextStyle
from youtube_automation.utils.exceptions import ConfigError

_DEFAULT_TITLE_SIZE = 96
_DEFAULT_CHANNEL_NAME_SIZE = 36
_DEFAULT_COLOR = "#FFFFFF"
_DEFAULT_STROKE_COLOR = "#000000"
_DEFAULT_OVERLAY_KEY_PREFIX = "thumbnail_text.overlay"
_SKILL_OVERLAY_CONFIG_PATH = "image_generation.gemini.thumbnail_text.overlay"
_SKILL_CONFIG_PATH_HINT = "config/skills/thumbnail.yaml"

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


def _font_fallback_guidance(key: str) -> str:
    return (
        "対処:\n"
        f"  1. config/skills/thumbnail.yaml の {key} に対応する\n"
        "     .ttf / .otf / .ttc ファイルのパスを設定する (絶対パス、または channel_dir からの相対パス)\n"
        '     例) font: {title: "assets/fonts/NotoSansJP-Bold.ttf"}\n'
        "  2. 利用可能なフォントの例: macOS は /System/Library/Fonts/、Google Fonts から\n"
        "     ダウンロードしたファイルを <channel_dir>/assets/fonts/ に置く運用を推奨\n"
        "  3. 決定的合成を使わない場合は AI 経路にフォールバックする\n"
        "     (SKILL.md「フォント安定化」参照。single_step は第2段の文字入り thumbnail prompt、\n"
        "     two_phase は thumbnail_text.font でフォントの雰囲気を指示できるが、書体の厳密な再現は保証されない)"
    )


def resolve_font_path(raw: str, *, channel_root: Path, key: str) -> Path:
    if not raw or not raw.strip():
        raise ConfigError(f"フォント指定が未設定です: {key}\n{_font_fallback_guidance(key)}")
    candidate = Path(raw.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = channel_root / candidate
    if not candidate.is_file():
        raise ConfigError(f"フォントファイルが見つかりません: {key} = {candidate}\n{_font_fallback_guidance(key)}")
    return candidate


def _validate_font_loadable(path: Path, *, size: int, key: str) -> None:
    try:
        ImageFont.truetype(str(path), size)
    except OSError as exc:
        raise ConfigError(f"フォントファイルを読み込めません: {path} ({exc})\n{_font_fallback_guidance(key)}") from exc


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


def _parse_anchor(raw: object, *, default: str, key: str) -> str:
    if raw in (None, ""):
        return default
    if not isinstance(raw, str):
        raise ConfigError(f"{key} は文字列で指定してください: {raw!r}")
    if raw not in _VALID_ANCHORS:
        raise ConfigError(f"{key} が不正です: {raw!r} (指定可能: {', '.join(sorted(_VALID_ANCHORS))})")
    return raw


def overlay_config_from_skill_config(skill_config: object) -> Mapping[str, object]:
    if not isinstance(skill_config, Mapping):
        raise ConfigError(f"thumbnail skill-config はマッピングで指定してください ({_SKILL_CONFIG_PATH_HINT})")
    image_generation = _mapping_at(skill_config, "image_generation", key="image_generation")
    gemini = _mapping_at(image_generation, "gemini", key="image_generation.gemini")
    thumbnail_text = _mapping_at(
        gemini,
        "thumbnail_text",
        key="image_generation.gemini.thumbnail_text",
    )
    return _mapping_at(
        thumbnail_text,
        "overlay",
        key=_SKILL_OVERLAY_CONFIG_PATH,
    )


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
    font_path = resolve_font_path(font_raw, channel_root=channel_root, key=font_key)
    size = _parse_int(section.get("size"), default=default_size, key=f"{key_prefix}.size", minimum=1)
    _validate_font_loadable(font_path, size=size, key=font_key)
    return TextStyle(
        font_path=font_path,
        size=size,
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
    key_prefix: str = _DEFAULT_OVERLAY_KEY_PREFIX,
) -> OverlaySpec:
    if not isinstance(overlay_config, Mapping):
        raise ConfigError(f"{key_prefix} はマッピングで指定してください ({_SKILL_CONFIG_PATH_HINT})")

    font_cfg = _mapping_at(overlay_config, "font", key=f"{key_prefix}.font")
    title_cfg = _mapping_at(overlay_config, "title", key=f"{key_prefix}.title")
    channel_cfg = _mapping_at(overlay_config, "channel_name", key=f"{key_prefix}.channel_name")
    title_font_raw = _font_path_value(font_cfg, "title", key=f"{key_prefix}.font.title")

    title_style = _build_text_style(
        title_cfg,
        font_raw=title_font_raw,
        channel_root=channel_root,
        key_prefix=f"{key_prefix}.title",
        font_key=f"{key_prefix}.font.title",
        default_size=_DEFAULT_TITLE_SIZE,
        default_stroke_width=4,
    )

    channel_name_style: TextStyle | None = None
    if with_channel_name:
        channel_font_raw = _font_path_value(font_cfg, "channel_name", key=f"{key_prefix}.font.channel_name")
        if not channel_font_raw:
            channel_font_raw = title_font_raw
        channel_name_style = _build_text_style(
            channel_cfg,
            font_raw=channel_font_raw,
            channel_root=channel_root,
            key_prefix=f"{key_prefix}.channel_name",
            font_key=f"{key_prefix}.font.channel_name",
            default_size=_DEFAULT_CHANNEL_NAME_SIZE,
            default_stroke_width=0,
        )

    layout = _mapping_at(overlay_config, "layout", key=f"{key_prefix}.layout")
    anchor = _parse_anchor(layout.get("anchor"), default="bottom-center", key=f"{key_prefix}.layout.anchor")

    line_spacing = _parse_positive_float(
        layout.get("line_spacing"),
        default=1.15,
        key=f"{key_prefix}.layout.line_spacing",
    )

    return OverlaySpec(
        title_style=title_style,
        channel_name_style=channel_name_style,
        anchor=anchor,
        margin_x=_parse_int(layout.get("margin_x"), default=64, key=f"{key_prefix}.layout.margin_x"),
        margin_y=_parse_int(layout.get("margin_y"), default=48, key=f"{key_prefix}.layout.margin_y"),
        line_spacing=line_spacing,
        gap=_parse_int(layout.get("gap"), default=24, key=f"{key_prefix}.layout.gap"),
    )
