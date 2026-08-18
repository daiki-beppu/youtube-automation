"""Localization and scene-phrase validation helpers."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List

from youtube_automation.core.adapters.runtime import format_localized_duration_display
from youtube_automation.domains.metadata.descriptions import build_short_description
from youtube_automation.domains.metadata.titles import (
    _referenced_placeholders,
    format_title_template,
)
from youtube_automation.domains.uploads.preflight import requires_scene_phrases

LOCALIZED_TITLE_PLACEHOLDERS = frozenset({"scene_phrase", "activities", "scene_emoji", "duration_display"})
_DURATION_LITERAL_PREFIX = r"(?<!\w)\d+(?:[.,]\d+)?\s*"
_JAPANESE_DURATION_PARTICLE = r"(?:の|を|に|は|が|と|で|へ|も)"
_STATIC_DURATION_LITERAL = re.compile(
    rf"{_DURATION_LITERAL_PREFIX}(?:"
    r"(?:hours?|hrs?|std\.?|stunden?|minutes?|mins?|min\.?)(?!\w)"
    rf"|(?:時間|分)(?=$|[^\w]|{_JAPANESE_DURATION_PARTICLE}(?=$|[^\w])))",
    re.IGNORECASE,
)
_LOCALIZED_STATIC_HOUR_LITERAL = {
    "fr": re.compile(rf"{_DURATION_LITERAL_PREFIX}heures?(?!\w)", re.IGNORECASE),
    "es": re.compile(rf"{_DURATION_LITERAL_PREFIX}horas?(?!\w)", re.IGNORECASE),
    "it": re.compile(rf"{_DURATION_LITERAL_PREFIX}(?:ora|ore)(?!\w)", re.IGNORECASE),
}


def _find_static_duration_literal(template: str, locale: object) -> re.Match[str] | None:
    matching_template = unicodedata.normalize("NFC", template)
    static_duration = _STATIC_DURATION_LITERAL.search(matching_template)
    if static_duration is not None or not isinstance(locale, str):
        return static_duration
    base_locale = locale.strip().replace("_", "-").casefold().split("-", 1)[0]
    localized_pattern = _LOCALIZED_STATIC_HOUR_LITERAL.get(base_locale)
    return localized_pattern.search(matching_template) if localized_pattern is not None else None


def build_short_localizations(
    config,
    *,
    collection_name: str,
    theme: str,
    cc_video_url: str,
) -> Dict[str, Dict[str, str]]:
    """Shorts 用 localizations を生成する（`generate_shorts_metadata` / bulk_update 共通）.

    - `short_title_template` を持たない言語は skip（plan 要件 #5）.
    - `short_description_template` が無い言語は `build_short_description` フォールバック.
    - `theme` を必須引数にして、bulk_update が theme 抜き(`""`) で初回 upload の
      タイトルを破壊する事故（AI-NEW-bulk-update-loc-L161）を構造的に防ぐ.
    """
    loc_config = config.localizations.data
    if not loc_config:
        return {}

    channel_name = config.meta.channel_name
    default_tagline = config.meta.tagline
    localizations: Dict[str, Dict[str, str]] = {}

    for lang in loc_config.get("supported_languages", []):
        lang_data = loc_config.get("languages", {}).get(lang, {})
        title_tpl = lang_data.get("short_title_template")
        if not title_tpl:
            continue

        loc_title = title_tpl.format(
            theme=theme,
            channel_name=channel_name,
            collection_name=collection_name,
        )

        desc_data = lang_data.get("description", {}) or {}
        tagline = desc_data.get("tagline", default_tagline)
        desc_tpl = lang_data.get("short_description_template")
        if desc_tpl:
            loc_desc = desc_tpl.format(
                collection_name=collection_name,
                channel_name=channel_name,
                cc_video_url=cc_video_url,
                tagline=tagline,
            )
        else:
            loc_desc = build_short_description(
                config,
                collection_name=collection_name,
                cc_video_url=cc_video_url,
            )

        localizations[lang] = {
            "title": loc_title,
            "description": loc_desc[:5000],
        }
    return localizations


def _localized_title_values(
    *,
    scene_phrase: str,
    activities: str,
    scene_emoji: str,
    duration_display: str,
) -> Dict[str, str]:
    """localizations の title_template に渡す values を組み立てる."""
    return {
        "scene_phrase": scene_phrase,
        "activities": activities,
        "scene_emoji": scene_emoji,
        "duration_display": duration_display,
    }


def validate_localizations_title_templates(loc_data: Dict) -> List[str]:
    """localizations.json の title_template 群を許可プレースホルダで検証する.

    channel-new / channel-import が生成した `config/localizations.json` が
    アップロード時まで気づけない不正プレースホルダ（例: `{axis_label}`）を
    含んでいないか、生成直後の config 検証で検出するための
    ヘルパー（#1471）。

    Args:
        loc_data: localizations.json の全量 dict（`config.localizations.data`）

    Returns:
        違反メッセージのリスト。空なら全言語合格。
    """
    errors: List[str] = []
    languages = loc_data.get("languages")
    if not isinstance(languages, dict):
        return errors
    for lang, lang_data in languages.items():
        if not isinstance(lang_data, dict):
            continue
        template = lang_data.get("title_template")
        if not isinstance(template, str):
            continue
        static_duration = _find_static_duration_literal(template, lang)
        if static_duration:
            errors.append(
                f"languages.{lang}.title_template: 固定尺 {static_duration.group(0)!r} が含まれています。\n"
                "  → 固定値を `{duration_display}` に置き換えて、実マスター尺を表示してください。\n"
                f"  → テンプレート: {template}"
            )
        unknown = _referenced_placeholders(template) - LOCALIZED_TITLE_PLACEHOLDERS
        if unknown:
            errors.append(
                f"languages.{lang}.title_template: 使用できないプレースホルダ {sorted(unknown)} が含まれています。\n"
                f"  → 使用可能なキー: {sorted(LOCALIZED_TITLE_PLACEHOLDERS)}\n"
                f"  → テンプレート: {template}"
            )
    return errors


@dataclass(frozen=True)
class SceneTitleViolation:
    """多言語タイトルの codepoint 超過違反（100 codepoint 上限）."""

    lang: str
    length: int
    excess: int
    fixed_length: int
    scene_phrase_length: int
    title: str
    template: str


def validate_scene_phrases(
    scene_phrases: Dict[str, str],
    config,
    duration_seconds: int | float | None,
    scene_emoji: str = "",
) -> List[SceneTitleViolation]:
    """scene_phrases を localizations の全言語で試算し、100 codepoint 超過を一括検出する.

    `/video --describe` など `workflow-state.json` への書き込み前に呼ぶことで、
    アップロード時 preflight まで超過発覚を遅らせず、全言語分をまとめて検査できる.
    単一言語チャンネルでは localizations 用の scene_phrases を生成しないため、
    空の scene_phrases を許容して空リストを返す.

    Args:
        scene_phrases: {"en": ..., "ja": ..., ...} コレクション別の感情フレーズ翻訳
        config: `load_config()` の戻り値
        duration_seconds: primary title と共有する実マスター秒数。生成前検証では予定秒数。

    Returns:
        違反のリスト。空なら全言語 100 codepoint 以内.

    Raises:
        ValueError: 多言語チャンネルで scene_phrases が一部言語で欠落している場合、
            または `localizations.json` に `title_template` が無い言語がある場合.
    """
    violations, _ = _validate_and_format_scene_titles(
        scene_phrases,
        config,
        duration_seconds,
        scene_emoji=scene_emoji,
    )
    return violations


def _validate_and_format_scene_titles(
    scene_phrases: Dict[str, str],
    config,
    duration_seconds: int | float,
    *,
    scene_emoji: str,
) -> tuple[List[SceneTitleViolation], Dict[str, str]]:
    """多言語タイトルを一度だけ検証・生成し、service と結果を共有する."""
    loc_config = config.localizations.data
    supported = loc_config.get("supported_languages", [])

    # 単一言語チャンネルは scene_phrases 不要（populate も no-op）#1470
    if not requires_scene_phrases(supported):
        return [], {}

    missing_langs = [lang for lang in supported if not scene_phrases.get(lang)]
    if missing_langs:
        raise ValueError(
            "scene_phrases に翻訳が不足しています。"
            f"不足言語: {missing_langs}\n"
            "→ コレクションの workflow-state.json に "
            "`scene_phrases: {en: ..., ja: ..., ...}` を populate してください。\n"
            "→ 既存例: collections/live/20260322-rjn-city-collection/workflow-state.json"
        )

    desc_metadata = config.content.descriptions.metadata
    best_for_line = desc_metadata.get("best_for", "Study, Focus, Late Night")

    violations: List[SceneTitleViolation] = []
    titles: Dict[str, str] = {}
    for lang in supported:
        lang_data = loc_config["languages"].get(lang, {})
        title_tpl = lang_data.get("title_template")
        if not title_tpl:
            raise ValueError(f"localizations.json: language '{lang}' に title_template が無い")
        activities = lang_data.get("activities", best_for_line)
        scene = scene_phrases[lang]
        title_placeholders = _referenced_placeholders(title_tpl)
        if "duration_display" in title_placeholders and duration_seconds is None:
            raise ValueError(
                "localizations の title_template に {duration_display} があるため、"
                "config/channel/audio.json の audio.target_duration_min が必要です"
            )
        duration_display = (
            format_localized_duration_display(duration_seconds, lang)
            if "duration_display" in title_placeholders and duration_seconds is not None
            else ""
        )
        title = format_title_template(
            title_tpl,
            _localized_title_values(
                scene_phrase=scene,
                activities=activities,
                scene_emoji=scene_emoji,
                duration_display=duration_display,
            ),
            context=f"localizations.json: language '{lang}' の title_template",
        )
        titles[lang] = title
        if len(title) > 100:
            fixed_title = format_title_template(
                title_tpl,
                _localized_title_values(
                    scene_phrase="",
                    activities=activities,
                    scene_emoji=scene_emoji,
                    duration_display=duration_display,
                ),
                context=f"localizations.json: language '{lang}' の title_template",
            )
            fixed_length = len(fixed_title)
            violations.append(
                SceneTitleViolation(
                    lang=lang,
                    length=len(title),
                    excess=len(title) - 100,
                    fixed_length=fixed_length,
                    scene_phrase_length=len(title) - fixed_length,
                    title=title,
                    template=title_tpl,
                )
            )
    return violations, titles


def format_scene_title_violations(violations: List[SceneTitleViolation]) -> str:
    """違反リストを人間可読な複数行テキストに整形する（CLI / エラーメッセージ共通）."""
    return "\n".join(
        f"  - [{v.lang}] {v.length} codepoints "
        f"(+{v.excess}; fixed={v.fixed_length}c; scene_phrase={v.scene_phrase_length}c): {v.title}"
        for v in violations
    )
