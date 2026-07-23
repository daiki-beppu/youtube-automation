"""Description generation helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

DESCRIPTIONS_MD_EXPECTED_HEADINGS = (
    "タイトル案",
    "Complete Collection 概要欄",
    "タグ（YouTube タグ欄）",
)


def extract_descriptions_md_section(text: str, heading: str) -> str | None:
    """Return the markdown body immediately under a level-two heading."""
    match = re.search(rf"^##[ \t]+{re.escape(heading)}[ \t]*\n+```\n(.*?)```", text, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else None


def missing_descriptions_md_headings(text: str) -> list[str]:
    """Return required headings absent from a descriptions document."""
    return [
        heading
        for heading in DESCRIPTIONS_MD_EXPECTED_HEADINGS
        if extract_descriptions_md_section(text, heading) is None
    ]


def build_descriptions_md_parse_diagnostics(text: str, missing_headings: Sequence[str] | None = None) -> str:
    """Explain a descriptions.md heading mismatch in a user-actionable form."""
    found_headings = extract_level2_headings(text)
    missing_source = missing_headings if missing_headings is not None else missing_descriptions_md_headings(text)
    missing = list(dict.fromkeys(missing_source))
    return "\n".join(
        [
            "期待する見出し（完全一致）:",
            _format_heading_list(DESCRIPTIONS_MD_EXPECTED_HEADINGS),
            "不足/不一致の見出し:",
            _format_heading_list(missing),
            "検出した ## 見出し:",
            _format_heading_list(found_headings),
            "修正例:",
            "  ## タイトル案",
            "  ```",
            "  公開タイトル",
            "  ```",
            "  ## Complete Collection 概要欄",
            "  ```",
            "  概要欄本文",
            "  ```",
            "  ## タグ（YouTube タグ欄）",
            "  ```",
            "  tag one, tag two",
            "  ```",
            DESCRIPTIONS_MD_RECREATE_GUIDE,
        ]
    )


DESCRIPTIONS_MD_RECREATE_GUIDE = (
    "→ 手書きファイルを直接直すのではなく、正規フローで作り直してください:\n"
    "  1. /video-description を再実行する\n"
    "  2. 生成された 20-documentation/descriptions.md を確認する\n"
    "  3. 必要なら生成後の本文だけを調整してから再アップロードする\n"
    "  必須セクション: `## タイトル案` / `## Complete Collection 概要欄` / `## タグ（YouTube タグ欄）`"
)


def extract_level2_headings(text: str) -> list[str]:
    return [match.group(1).strip() for match in re.finditer(r"^##\s+(.+?)\s*$", text, re.MULTILINE)]


def _format_heading_list(headings: Sequence[str]) -> str:
    if not headings:
        return "  - (なし)"
    return "\n".join(f"  - ## {heading}" for heading in headings)


def _format_short_duration_phrase(config) -> str:
    """`config.audio.target_duration_min` から「2 hours」等の文字列を組み立てる.

    `target_duration_min is None` のときは `round(min / 60)` で TypeError に
    ならないよう "Full collection" にフォールバックする（plan §152）。
    """
    target_min = config.audio.target_duration_min
    if target_min is None:
        return "Full collection"
    hours = round(target_min / 60)
    return f"{hours} hour" if hours == 1 else f"{hours} hours"


def build_short_description(
    config,
    *,
    collection_name: str,
    cc_video_url: str,
) -> str:
    """Shorts デフォルト description（fallback と default 両方で使う共通組み立て）.

    `cc_video_url` が空なら `♫` 行を含めない（plan 要件 #3 / アンチパターン #5）。
    末尾に `#Shorts` を必ず付ける（YouTube 検出最適化）。
    """
    duration_phrase = _format_short_duration_phrase(config)
    parts = [
        f"{collection_name} ({duration_phrase}) | {config.meta.channel_name}",
        "",
    ]
    if cc_video_url:
        parts.append(f"♫ Full → {cc_video_url}")
        parts.append("")
    parts.append("#Shorts")
    return "\n".join(parts)


def build_complete_collection_description(
    *,
    title: str,
    timestamp_body: str,
    opening: str,
    sub_opening: str,
    usage_header: str,
    usage_lines: Iterable[str],
    perfect_for_header: str,
    perfect_for_lines: str,
    channel_link_header: str,
    cta_subscribe: str,
    tagline: str,
    hashtag_line: str,
) -> str:
    """Assemble a complete description from resolved content parts."""
    parts = [f"🎵 {title}", ""]
    if timestamp_body:
        parts.append(timestamp_body)
    parts.extend(
        [
            "",
            opening,
            sub_opening,
            "",
            usage_header,
            *usage_lines,
            "",
            f"{perfect_for_header}\n{perfect_for_lines}",
            "",
            channel_link_header,
            cta_subscribe,
            tagline,
            "",
            hashtag_line,
        ]
    )
    return "\n".join(parts)
