"""Description generation helpers."""

from __future__ import annotations

from collections.abc import Iterable


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
