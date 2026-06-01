"""imagegen Shared prompt schema (14 項目) と既存 skill-config の bridge.

issue #654: 将来 imagegen 公式 SKILL.md の 14 項目 Shared prompt schema 形式へ
段階移行するための試験導入レイヤ。本モジュールはヘルパ提供のみで、
実本番のプロンプト構築フロー (``image_provider.composition`` /
``scripts.generate_image``) からは **未接続**。実本番経路の schema 化は
skill-config 全体の管理方法見直し epic とセットで再評価する。

設計判断と採用範囲は ``docs/skill-design/ADR-001-thumbnail-prompt-schema.md``、
14 項目と skill-config キーの対応表は
``.claude/skills/thumbnail/references/prompt-schema.md`` を参照。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["PromptSchema", "render", "from_skill_config"]


@dataclass(frozen=True)
class PromptSchema:
    """imagegen Shared prompt schema (14 項目) の Python 表現.

    各項目は imagegen 公式 SKILL.md と同じ順序・同じ意味づけ。未指定項目は
    ``None`` / 空 tuple として残し、``render()`` でスキップされる。
    """

    use_case: str | None = None
    asset_type: str | None = None
    primary_request: str | None = None
    input_images: tuple[str, ...] = ()
    scene: str | None = None
    subject: str | None = None
    style: str | None = None
    composition: str | None = None
    lighting: str | None = None
    color: str | None = None
    materials: str | None = None
    text: str | None = None
    constraints: str | None = None
    avoid: str | None = None


_FIELD_LABELS: tuple[tuple[str, str], ...] = (
    ("use_case", "Use case"),
    ("asset_type", "Asset type"),
    ("primary_request", "Primary request"),
    ("input_images", "Input images"),
    ("scene", "Scene"),
    ("subject", "Subject"),
    ("style", "Style"),
    ("composition", "Composition"),
    ("lighting", "Lighting"),
    ("color", "Color"),
    ("materials", "Materials"),
    ("text", "Text"),
    ("constraints", "Constraints"),
    ("avoid", "Avoid"),
)


def render(schema: PromptSchema) -> str:
    """``PromptSchema`` を imagegen 形式の ``Label: value`` テキストにレンダリングする.

    未指定 (``None`` / 空文字列 / 空 tuple) の項目はスキップ。改行区切りで
    Codex / imagegen 互換の構造化プロンプトを返す。
    """
    lines: list[str] = []
    for attr, label in _FIELD_LABELS:
        value = getattr(schema, attr)
        if value is None:
            continue
        if isinstance(value, tuple):
            if not value:
                continue
            rendered: str = ", ".join(str(v) for v in value)
        elif isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                continue
            rendered = stripped
        else:
            rendered = str(value)
        lines.append(f"{label}: {rendered}")
    return "\n".join(lines)


def from_skill_config(skill_config: dict[str, Any]) -> PromptSchema:
    """skill-config (``load_skill_config("thumbnail")`` の戻り値) から
    ``PromptSchema`` を機械的に組み立てる bridge.

    対応マッピングは ``.claude/skills/thumbnail/references/prompt-schema.md``
    に明文化されている。未設定キーは ``None`` / 空 tuple として残るため、
    呼び出し側 (試験フェーズ) はここから返った schema に追加情報を
    ``dataclasses.replace`` 等でマージしてから ``render()`` に渡す想定。

    本関数自体は実本番のプロンプト構築フローから呼ばれない (issue #654 §制約)。
    """
    cfg = skill_config if isinstance(skill_config, dict) else {}
    generation = _as_dict(cfg.get("image_generation"))
    gemini = _as_dict(generation.get("gemini"))
    composition_rules = _as_dict(gemini.get("composition_rules"))
    thumbnail_text = _as_dict(gemini.get("thumbnail_text"))
    references = _as_dict(gemini.get("reference_images"))
    fixed_character = _as_dict(gemini.get("fixed_character"))

    return PromptSchema(
        use_case="product-mockup (YouTube thumbnail variant)",
        asset_type="YouTube thumbnail (1280x720, 16:9, JPEG)",
        primary_request=_string_or_none(gemini.get("prompt_prefix")),
        input_images=_input_images_from(references.get("default")),
        scene=_join_nonempty(
            composition_rules.get("environment"),
            composition_rules.get("background"),
        ),
        subject=_subject_from(fixed_character, composition_rules),
        style=_string_or_none(gemini.get("style")),
        composition=_join_nonempty(
            composition_rules.get("character_size"),
            composition_rules.get("character_pose"),
            thumbnail_text.get("copy_position"),
        ),
        lighting=None,
        color=_join_nonempty(
            gemini.get("brand_background"),
            thumbnail_text.get("color"),
        ),
        materials=_string_or_none(thumbnail_text.get("decoration")),
        text=_text_from(thumbnail_text, composition_rules.get("text_lines")),
        constraints=_string_or_none(composition_rules.get("text_lines")),
        avoid=_string_or_none(composition_rules.get("ng_actions")),
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _input_images_from(default: Any) -> tuple[str, ...]:
    if isinstance(default, str):
        return (default,) if default else ()
    if isinstance(default, list):
        return tuple(str(p) for p in default if isinstance(p, str) and p)
    return ()


def _join_nonempty(*values: Any) -> str | None:
    parts: list[str] = []
    for v in values:
        if isinstance(v, str):
            stripped = v.strip()
            if stripped:
                parts.append(stripped)
    if not parts:
        return None
    return ". ".join(parts)


def _subject_from(
    fixed_character: dict[str, Any],
    composition_rules: dict[str, Any],
) -> str | None:
    parts: list[str] = []
    for key in ("species", "description", "outfit", "accessories", "expression", "pose"):
        v = fixed_character.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    pose = composition_rules.get("character_pose")
    if isinstance(pose, str) and pose.strip():
        parts.append(pose.strip())
    if not parts:
        return None
    return ". ".join(parts)


def _text_from(thumbnail_text: dict[str, Any], text_lines: Any) -> str | None:
    parts: list[str] = []
    for key in ("title_format", "title_prefix", "channel_name", "channel_name_style"):
        v = thumbnail_text.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    font = thumbnail_text.get("font")
    if isinstance(font, dict):
        for fk in ("copy", "genre_tag"):
            fv = font.get(fk)
            if isinstance(fv, str) and fv.strip():
                parts.append(f"{fk}: {fv.strip()}")
    if isinstance(text_lines, str) and text_lines.strip():
        parts.append(text_lines.strip())
    if not parts:
        return None
    return ". ".join(parts)
