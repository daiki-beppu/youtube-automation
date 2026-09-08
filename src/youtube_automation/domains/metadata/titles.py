"""Pure title-template and collection-title helpers."""

from __future__ import annotations

import re
import string
from collections.abc import Mapping, Sequence
from typing import Dict

from youtube_automation.core.errors import ValidationError

# `pattern-b1-` のような variation 接尾辞を保持する。
_PATTERN_KEY_RE = re.compile(r"^\d+-pattern-([a-d]\d*)-", re.IGNORECASE)
_EXTRA_VARIATION_RE = re.compile(r"^\d+-extra-v(\d+)(?:[-.]|$)", re.IGNORECASE)


def requires_scene_phrases(supported_languages: Sequence[str]) -> bool:
    """チャンネルが workflow-state.json.scene_phrases を必要とするかどうか (#1470).

    scene_phrases は多言語 localizations のタイトル生成にのみ使われるため、
    `supported_languages` が 1 言語以下のチャンネルでは不要。populate
    （`yt-populate-scene-phrases` の no-op 判定）と検証側（preflight /
    metadata audit / localizations 生成）はこの判定を共有する。
    """
    return len(set(supported_languages)) > 1


def missing_scene_phrase_languages(
    scene_phrases: Mapping[str, object], supported_languages: Sequence[str]
) -> list[str]:
    """Return missing multilingual phrases once per language, in configured order."""
    if not requires_scene_phrases(supported_languages):
        return []
    required = dict.fromkeys(supported_languages)
    return [language for language in required if not scene_phrases.get(language)]


def build_collection_title(template: str, values: Dict[str, str], *, context: str) -> str:
    """Resolve a collection title from already-resolved template values."""
    title = format_title_template(template, values, context=context)
    if len(title) > 100:
        raise ValueError(
            f"生成したタイトルが {len(title)} codepoint と 100 を超過: "
            f"\n  {title}\n"
            "→ config/channel/content.json の title.theme_scenes の scene を短く書き直してください"
        )
    return title


def build_short_title(collection_name: str, channel_name: str) -> str:
    """Build and validate the fixed Shorts title."""
    title = f"{collection_name} ✦ {channel_name} #Shorts"
    if len(title) > 100:
        raise ValueError(
            f"生成した Shorts タイトルが {len(title)} codepoint と 100 を超過: "
            f"{title}\n→ コレクションディレクトリ名（_extract_collection_name 経路）を短縮してください"
        )
    return title


def _extract_pattern_key(filename: str) -> str | None:
    """ファイル名から pattern_key（'a'|'b1'|'d2' 等）を抽出する。マッチしなければ None."""
    m = _PATTERN_KEY_RE.match(filename)
    if not m:
        return None
    return m.group(1).lower()


def _extract_extra_variation(filename: str) -> str | None:
    """`01-extra-v2-...` から extra variation 番号を抽出する。"""
    m = _EXTRA_VARIATION_RE.match(filename)
    if not m:
        return None
    return m.group(1)


def _referenced_placeholders(template: str) -> set[str]:
    """format テンプレートが参照するフィールド名の集合を返す（`{a.b}` / `{a[0]}` は `a` に正規化）."""
    referenced: set[str] = set()
    for _literal, field_name, _spec, _conv in string.Formatter().parse(template):
        if field_name:
            referenced.add(field_name.split(".")[0].split("[")[0])
    return referenced


def format_title_template(template: str, values: Dict[str, str], *, context: str) -> str:
    """title テンプレートを整形する。未知プレースホルダは actionable な ValidationError にする.

    `str.format()` をそのまま呼ぶと、テンプレートが提供キー以外のプレースホルダ
    （例: `{adjective}`）を含むときに opaque な `KeyError` を送出し、upload 全体が
    深部でクラッシュする（#574）。本ヘルパーは事前に未知プレースホルダを検出し、
    「使用不可プレースホルダ名 + 許可キー一覧」を含む `ValidationError` に変換する。

    Args:
        template: format 文字列
        values: 許可キー → 値の dict（このキー集合のみ許容）
        context: エラーメッセージに添える文脈（どのテンプレートか）

    Raises:
        ValidationError: テンプレートが `values` に無いプレースホルダを含むとき。
    """
    allowed = set(values)
    unknown = _referenced_placeholders(template) - allowed
    if unknown:
        raise ValidationError(
            f"{context}: 使用できないプレースホルダ {sorted(unknown)} が含まれています。\n"
            f"→ 使用可能なキー: {sorted(allowed)}\n"
            f"→ テンプレート: {template}"
        )
    return template.format(**values)
